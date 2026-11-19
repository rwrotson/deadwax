import asyncio
import hashlib
import importlib.util
import logging
import random
import re
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from deadwax.core import (
    BlockedError,
    ConfigurationError,
    NotFoundError,
    RateLimitedError,
    SourceError,
    pause_adapter_timeout,
    trace,
)
from deadwax.sources._http.browser import BrowserFetcher
from deadwax.sources._http.cache import ResponseCache, cache_key
from deadwax.sources._http.challenge import detect_challenge
from deadwax.sources._http.impersonate import ImpersonateFetcher
from deadwax.sources._http.messages import Fetcher, Request, Response, TransportError
from deadwax.sources._http.nodriver import NodriverFetcher
from deadwax.sources._http.plain import HttpxFetcher
from deadwax.sources._http.profiles import CHROME, Profile, api_headers, browser_headers
from deadwax.sources._http.ratelimit import HostLimiters, Sleep
from deadwax.sources._http.retry import RETRY_STATUSES, RetryPolicy
from deadwax.sources._http.sessions import BROWSER_STEPS, BrowserSessions, FetcherFactory
from deadwax.sources.config import DIRECT, Escalation, HttpSettings, SourcesConfig

logger = logging.getLogger(__name__)

_NOT_FOUND = 404

# Header of the cache entry that remembers a page refused by bot protection.
_BLOCKED_HEADER = "x-deadwax-blocked"

# Header of that entry naming the route the page was refused on; a block on another
# route, such as before switching a source to 'direct', does not apply.
_ROUTE_HEADER = "x-deadwax-route"
_ENVIRONMENT_ROUTE = "environment"
_TOO_MANY_REQUESTS = 429

# Extras that provide each escalation step.
_EXTRA_PACKAGES = {
    Escalation.IMPERSONATE: "curl_cffi",
    Escalation.BROWSER: "patchright",
    Escalation.NODRIVER: "nodriver",
}


def _impersonate(settings: HttpSettings, proxy: str | None) -> Fetcher:
    return ImpersonateFetcher(
        timeout=settings.timeout,
        max_bytes=settings.max_response_bytes,
        proxy=proxy,
    )


def _nodriver(settings: HttpSettings, proxy: str | None) -> Fetcher:
    return NodriverFetcher(
        timeout=settings.timeout,
        max_bytes=settings.max_response_bytes,
        proxy=proxy,
        headless=settings.browser_headless,
        browser_path=settings.nodriver_browser_path,
        sandbox=settings.nodriver_sandbox,
        challenge_wait=settings.browser_challenge_wait,
        manual_challenge_wait=settings.headed_challenge_wait,
        profile_dir=settings.nodriver_profile_dir,
    )


def _browser(settings: HttpSettings, proxy: str | None) -> Fetcher:
    return BrowserFetcher(
        timeout=settings.timeout,
        max_bytes=settings.max_response_bytes,
        proxy=proxy,
        headless=settings.browser_headless,
        channel=settings.patchright_channel,
        challenge_wait=settings.browser_challenge_wait,
        manual_challenge_wait=settings.headed_challenge_wait,
        profile_dir=settings.patchright_profile_dir,
    )


def _installed(package: str) -> bool:
    return importlib.util.find_spec(package) is not None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def escalation_steps(
    selected: tuple[Escalation, ...],
    installed: Callable[[str], bool] = _installed,
) -> list[Escalation]:
    """Return the source's transports in order, omitting missing optional packages."""
    return [
        step for step in selected if step is Escalation.HTTPX or installed(_EXTRA_PACKAGES[step])
    ]


def route(proxy: str | None) -> str:
    """Name the way requests leave for a proxy setting, without credentials."""
    if proxy is None:
        return _ENVIRONMENT_ROUTE
    if proxy == DIRECT:
        return DIRECT
    parts = urlsplit(proxy)
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"


def route_profile(directory: Path | None, route_name: str) -> Path | None:
    """Return the persistent profile of a route; Chrome cannot open one profile twice."""
    if directory is None or route_name == _ENVIRONMENT_ROUTE:
        return directory
    suffix = re.sub(r"[^A-Za-z0-9.]+", "-", urlsplit(route_name).netloc or route_name)
    return directory.with_name(f"{directory.name}-{suffix.strip('-')}")


def redact(url: str, secret_params: Collection[str]) -> str:
    """Remove secret query parameters from a URL."""
    if not secret_params:
        return url
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in query if k not in secret_params]
    if len(kept) == len(query):
        return url
    return urlunsplit(parts._replace(query=urlencode(kept)))


@dataclass(slots=True)
class HttpResources:
    """Objects shared by the clients of one lookup; tests replace transports and time."""

    limiters: HostLimiters = field(default_factory=HostLimiters)
    cache: ResponseCache | None = None
    transport: httpx.AsyncBaseTransport | None = None
    escalations: Mapping[Escalation, FetcherFactory] = field(
        default_factory=lambda: {
            Escalation.IMPERSONATE: _impersonate,
            Escalation.BROWSER: _browser,
            Escalation.NODRIVER: _nodriver,
        },
    )
    installed: Callable[[str], bool] = _installed
    sleep: Sleep = asyncio.sleep
    now: Callable[[], datetime] = _utcnow
    rng: random.Random = field(default_factory=random.Random)
    sessions: BrowserSessions = field(default_factory=BrowserSessions)


@dataclass(slots=True)
class _Exchange:
    """What happened to one request, for its `http.request` event."""

    cache: str
    fetchers: list[str] = field(default_factory=list)
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class ClientSpec:
    """How one adapter talks to its source."""

    source: str
    profile: Profile = Profile.API
    headers: Mapping[str, str] = field(default_factory=dict)
    secret_params: frozenset[str] = frozenset()
    required_marker: bytes | None = None


class HttpClient:
    """Rate-limited, retrying, caching HTTP client of one adapter.

    Browser-profile clients try their configured transports when a page shows a challenge.
    A headless browser that meets a challenge retries headed, and the source stays headed.
    """

    def __init__(self, spec: ClientSpec, config: SourcesConfig, resources: HttpResources) -> None:
        self.spec = spec
        self._config = config
        self._settings = config.http.model_copy(
            update={"browser_headless": config.browser_headless(spec.source)},
        )
        self._resources = resources
        self._proxy = config.proxy(spec.source)
        self._route = route(self._proxy)
        self._browser_settings = self._settings.model_copy(
            update={
                "patchright_profile_dir": route_profile(
                    self._settings.patchright_profile_dir,
                    self._route,
                ),
                "nodriver_profile_dir": route_profile(
                    self._settings.nodriver_profile_dir,
                    self._route,
                ),
            },
        )

        self._policy = RetryPolicy(
            retries=self._settings.retries,
            base=self._settings.retry_base,
            max_wait=self._settings.max_retry_wait,
        )

        profile_headers = (
            api_headers(self._settings.contact)
            if spec.profile is Profile.API
            else browser_headers(CHROME)
        )
        self._plain = HttpxFetcher(
            headers={**profile_headers, **spec.headers},
            timeout=self._settings.timeout,
            max_bytes=self._settings.max_response_bytes,
            transport=resources.transport,
            proxy=self._proxy,
        )

        self._steps = (
            escalation_steps(config.html_transports(spec.source), resources.installed)
            if spec.profile is Profile.BROWSER
            else [Escalation.HTTPX]
        )
        profile_policy = (
            f"{self._settings.patchright_channel}|{self._settings.browser_headless}|"
            f"{self._settings.patchright_profile_dir}|{self._settings.nodriver_profile_dir}|"
            f"{self._settings.headed_fallback}|{self._settings.headed_challenge_wait}"
        )
        self._policy_signature = (
            f"{','.join(self._steps)}:{hashlib.sha256(profile_policy.encode()).hexdigest()}"
        )
        self._escalated: dict[Escalation, Fetcher] = {}
        self._level = 0
        self._configured_headed = not self._settings.browser_headless
        self._headed = self._configured_headed
        self._unavailable = (
            [
                f"{step} unavailable: install {_EXTRA_PACKAGES[step]}"
                for step in config.html_transports(spec.source)
                if step not in self._steps and step is not Escalation.HTTPX
            ]
            if spec.profile is Profile.BROWSER
            else []
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close every transport the client opened."""
        await self._plain.aclose()
        for fetcher in self._escalated.values():
            await fetcher.aclose()
        self._escalated.clear()

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Send a GET request; see `request`."""
        return await self.request("GET", url, params=params, headers=headers)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> Response:
        """Return a 2xx response from the cache or the source.

        Raises `NotFoundError` on 404, `RateLimitedError` when the source keeps refusing,
        `BlockedError` when every transport meets a challenge, and `SourceError` otherwise.
        """
        request = Request(
            method=method,
            url=url,
            params=tuple((params or {}).items()),
            headers=tuple((headers or {}).items()),
            body=body,
            required_marker=self.spec.required_marker,
        )
        exchange = _Exchange(cache="off" if self._resources.cache is None else "miss")
        started = time.monotonic()
        try:
            response = await self._request(request, exchange)
        except SourceError as error:
            self._trace(request, exchange, started, None, error)
            raise
        self._trace(request, exchange, started, response, None)
        return self._check(response)

    def _trace(
        self,
        request: Request,
        exchange: _Exchange,
        started: float,
        response: Response | None,
        error: SourceError | None,
    ) -> None:
        fields: dict[str, object] = {
            "method": request.method,
            "url": redact(request.full_url, self.spec.secret_params),
            "cache": exchange.cache,
            "fetchers": exchange.fetchers,
            "attempts": exchange.attempts,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
        if response is not None:
            fields |= {
                "status": response.status,
                "final_url": response.url,
                "content_type": response.headers.get("content-type"),
                "bytes": len(response.content),
                "sha256": hashlib.sha256(response.content).hexdigest(),
            }
        if error is not None:
            fields["error"] = {"type": type(error).__name__, "message": str(error)}
        trace(logger, "http.request", **fields)

    async def _request(self, request: Request, exchange: _Exchange) -> Response:
        """Return the response from the cache or the source, without checking its status."""
        cache = self._resources.cache
        key = cache_key(self.spec.source, request, self.spec.secret_params)
        if cache is not None and (cached := await cache.get(key)) is not None:
            exchange.cache = "hit"
            blocked = cached.headers.get(_BLOCKED_HEADER)
            if blocked is None:
                return cached
            if (
                cached.headers.get(_ROUTE_HEADER, _ENVIRONMENT_ROUTE) == self._route
                and cached.headers.get("x-deadwax-transports") == self._policy_signature
            ):
                exchange.cache = "blocked"
                raise BlockedError(f"{blocked} (cached)", url=cached.url)
            exchange.cache = "miss"

        try:
            response = await self._fetch(request, exchange)
        except BlockedError as error:
            if cache is not None and error.url is not None:
                marker = Response(
                    url=error.url,
                    status=403,
                    content=b"",
                    headers={
                        _BLOCKED_HEADER: str(error),
                        _ROUTE_HEADER: self._route,
                        "x-deadwax-transports": self._policy_signature,
                    },
                )
                await cache.put(key, marker, self._config.cache.blocked_ttl)
            raise
        response = Response(
            url=redact(response.url, self.spec.secret_params),
            status=response.status,
            content=response.content,
            headers=response.headers,
        )
        if cache is not None and response.ok:
            await cache.put(key, response, self._config.ttl(self.spec.source))
        elif cache is not None and response.status == _NOT_FOUND:
            await cache.put(key, response, self._config.cache.not_found_ttl)
        return response

    def _check(self, response: Response) -> Response:
        if response.ok:
            return response
        if response.status == _NOT_FOUND:
            raise NotFoundError("not found", url=response.url)
        if response.status == _TOO_MANY_REQUESTS:
            raise RateLimitedError("too many requests", url=response.url)
        raise SourceError(f"HTTP {response.status}", url=response.url)

    def _fetcher(self, step: Escalation) -> Fetcher:
        if step is Escalation.HTTPX:
            return self._plain
        if step not in self._escalated:
            self._escalated[step] = self._resources.escalations[step](self._settings, self._proxy)
        return self._escalated[step]

    def _label(self, step: Escalation) -> str:
        if step is Escalation.HTTPX:
            return self._plain.name
        if step in BROWSER_STEPS and self._headed and not self._configured_headed:
            return f"{step}[headed]"
        return str(step)

    def _falls_back(self, step: Escalation) -> bool:
        """Whether a challenge in this headless browser step is retried headed."""
        return step in BROWSER_STEPS and not self._headed and self._settings.headed_fallback

    async def _fetch(self, request: Request, exchange: _Exchange) -> Response:
        safe_url = redact(request.full_url, self.spec.secret_params)
        reason = ""
        tried: list[str] = []
        challenged = False
        level = self._level
        while level < len(self._steps):
            step = self._steps[level]
            try:
                response = await self._attempt(step, request, safe_url, exchange)
            except TransportError as error:
                error.url = error.url or safe_url
                if level == len(self._steps) - 1:
                    raise
                self._unavailable.append(f"{self._label(step)} failed: {error}")
                trace(logger, "http.step_failed", step=step, reason=str(error))
                level += 1
                continue
            except SourceError as error:
                error.url = error.url or safe_url
                raise
            except ConfigurationError as error:
                await self._drop_step(level, error)
                continue
            label = self._label(step)
            tried.append(label)
            if (problem := self._problem(response, safe_url, label)) is None:
                self._level = level
                return response
            reason, challenge = problem
            challenged = challenged or challenge
            if challenge and self._falls_back(step):
                self._headed = True
                trace(logger, "http.headed_fallback", url=safe_url, fetcher=label)
                continue
            level += 1
        unavailable = f"; {'; '.join(self._unavailable)}" if self._unavailable else ""
        failure_type = BlockedError if challenged else SourceError
        raise failure_type(f"{reason} (tried {', '.join(tried)}{unavailable})", url=safe_url)

    def _problem(self, response: Response, safe_url: str, label: str) -> tuple[str, bool] | None:
        """Return why a page is unusable and whether it is a challenge, or None when usable."""
        if challenge := detect_challenge(response.status, response.headers, response.content):
            trace(logger, "http.challenge", url=safe_url, challenge=challenge, fetcher=label)
            return challenge, True
        if (
            self.spec.required_marker is not None
            and self.spec.required_marker not in response.content
        ):
            trace(logger, "http.page_incomplete", url=safe_url, fetcher=label)
            return "required page state missing", False
        return None

    async def _drop_step(self, level: int, error: ConfigurationError) -> None:
        """Skip one unavailable transport and continue with the next."""
        step = self._steps[level]
        trace(logger, "http.step_dropped", step=step, reason=str(error))
        self._unavailable.append(f"{step} unavailable: {error}")
        del self._steps[level]
        self._level = min(self._level, max(len(self._steps) - 1, 0))
        if (fetcher := self._escalated.pop(step, None)) is not None:
            await fetcher.aclose()

    def _should_retry(self, response: Response) -> bool:
        if response.status not in RETRY_STATUSES:
            return False
        return detect_challenge(response.status, response.headers, response.content) is None

    async def _fetch_once(self, step: Escalation, request: Request) -> Response:
        if step not in BROWSER_STEPS:
            return await self._fetcher(step).fetch(request)
        sessions = self._resources.sessions
        factory = self._resources.escalations[step]
        async with sessions.use(
            step,
            factory,
            self._browser_settings,
            self._proxy,
            headed=self._headed,
        ) as lease:
            if not lease.headed:
                return await lease.fetcher.fetch(request)

            # A visible browser may wait for a visitor; its requests are not adapter time.
            self._headed = True
            async with pause_adapter_timeout():
                return await lease.fetcher.fetch(request)

    async def _fetch_recorded(
        self,
        step: Escalation,
        request: Request,
        exchange: _Exchange,
    ) -> Response:
        try:
            return await self._fetch_once(step, request)
        finally:
            exchange.fetchers.append(self._label(step))

    async def _attempt(
        self,
        step: Escalation,
        request: Request,
        safe_url: str,
        exchange: _Exchange,
    ) -> Response:
        """Send one request through a transport, retrying on 429, 5xx, and network errors."""
        host = urlsplit(request.url).hostname or ""
        limiter = self._resources.limiters.get(host, self._config.rate(self.spec.source))
        rng = self._resources.rng
        attempt = 0

        while True:
            await limiter.acquire()
            exchange.attempts += 1
            try:
                response = await self._fetch_recorded(step, request, exchange)
            except TransportError as error:
                if attempt >= self._policy.retries:
                    raise
                delay = self._policy.backoff(attempt, rng)
                trace(logger, "http.retry", url=safe_url, error=str(error), delay_s=delay)
            else:
                if attempt >= self._policy.retries or not self._should_retry(response):
                    return response
                retry_after = response.headers.get("retry-after")
                delay = self._policy.delay(attempt, retry_after, rng, self._resources.now())
                if delay > self._policy.max_wait:
                    raise RateLimitedError(f"asked to wait {delay:.0f} s", url=safe_url)
                trace(logger, "http.retry", url=safe_url, status=response.status, delay_s=delay)
            await self._resources.sleep(delay)
            attempt += 1
