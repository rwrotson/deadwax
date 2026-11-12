import asyncio
import importlib.util
import logging
import random
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from deadwax.core import BlockedError, NotFoundError, RateLimitedError, SourceError
from deadwax.sources._http.browser import BrowserFetcher
from deadwax.sources._http.cache import ResponseCache, cache_key
from deadwax.sources._http.challenge import detect_challenge
from deadwax.sources._http.impersonate import ImpersonateFetcher
from deadwax.sources._http.messages import Fetcher, Request, Response, TransportError
from deadwax.sources._http.plain import HttpxFetcher
from deadwax.sources._http.profiles import CHROME, Profile, api_headers, browser_headers
from deadwax.sources._http.ratelimit import HostLimiters, Sleep
from deadwax.sources._http.retry import RETRY_STATUSES, RetryPolicy
from deadwax.sources.config import Escalation, HttpSettings, SourcesConfig

logger = logging.getLogger(__name__)

type FetcherFactory = Callable[[HttpSettings], Fetcher]

_NOT_FOUND = 404
_TOO_MANY_REQUESTS = 429

# Extras that provide each escalation step.
_EXTRA_PACKAGES = {Escalation.IMPERSONATE: "curl_cffi", Escalation.BROWSER: "playwright"}


def _impersonate(settings: HttpSettings) -> Fetcher:
    return ImpersonateFetcher(timeout=settings.timeout, max_bytes=settings.max_response_bytes)


def _browser(settings: HttpSettings) -> Fetcher:
    return BrowserFetcher(timeout=settings.timeout, max_bytes=settings.max_response_bytes)


def _installed(package: str) -> bool:
    return importlib.util.find_spec(package) is not None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def escalation_steps(
    setting: Escalation | None, installed: Callable[[str], bool] = _installed
) -> list[Escalation]:
    """Return the transports to try after plain httpx, weakest first.

    Unset means every installed one; an explicit setting keeps its own step even when the
    extra is missing, so that the missing extra is reported.
    """
    steps = [Escalation.IMPERSONATE, Escalation.BROWSER]
    if setting is None:
        return [step for step in steps if installed(_EXTRA_PACKAGES[step])]
    allowed = steps[: steps.index(setting) + 1] if setting is not Escalation.NONE else []
    return [step for step in allowed if step is setting or installed(_EXTRA_PACKAGES[step])]


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
        default_factory=lambda: {Escalation.IMPERSONATE: _impersonate, Escalation.BROWSER: _browser}
    )
    installed: Callable[[str], bool] = _installed
    sleep: Sleep = asyncio.sleep
    now: Callable[[], datetime] = _utcnow
    rng: random.Random = field(default_factory=random.Random)


@dataclass(frozen=True, slots=True)
class ClientSpec:
    """How one adapter talks to its source."""

    source: str
    profile: Profile = Profile.API
    headers: Mapping[str, str] = field(default_factory=dict)
    secret_params: frozenset[str] = frozenset()


class HttpClient:
    """Rate-limited, retrying, caching HTTP client of one adapter.

    Browser-profile clients escalate to stronger transports when a page shows a challenge
    and keep using the transport that worked.
    """

    def __init__(self, spec: ClientSpec, config: SourcesConfig, resources: HttpResources) -> None:
        self.spec = spec
        self._config = config
        self._settings = config.http
        self._resources = resources
        self._policy = RetryPolicy(
            retries=self._settings.retries, max_wait=self._settings.max_retry_wait
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
        )
        self._steps: list[Escalation] = (
            escalation_steps(self._settings.escalation, resources.installed)
            if spec.profile is Profile.BROWSER
            else []
        )
        self._escalated: dict[Escalation, Fetcher] = {}
        self._level = 0

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
        )
        cache = self._resources.cache
        key = cache_key(self.spec.source, request, self.spec.secret_params)
        if cache is not None and (cached := await cache.get(key)) is not None:
            logger.debug("%s cache hit %s", self.spec.source, cached.url)
            return self._check(cached)

        response = await self._fetch(request)
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
        return self._check(response)

    def _check(self, response: Response) -> Response:
        if response.ok:
            return response
        if response.status == _NOT_FOUND:
            raise NotFoundError("not found", url=response.url)
        if response.status == _TOO_MANY_REQUESTS:
            raise RateLimitedError("too many requests", url=response.url)
        raise SourceError(f"HTTP {response.status}", url=response.url)

    def _fetcher(self, level: int) -> Fetcher:
        if level == 0:
            return self._plain
        step = self._steps[level - 1]
        if step not in self._escalated:
            self._escalated[step] = self._resources.escalations[step](self._settings)
        return self._escalated[step]

    async def _fetch(self, request: Request) -> Response:
        safe_url = redact(request.full_url, self.spec.secret_params)
        reason = ""
        tried: list[str] = []
        for level in range(self._level, len(self._steps) + 1):
            fetcher = self._fetcher(level)
            tried.append(fetcher.name)
            try:
                response = await self._attempt(fetcher, request, safe_url)
            except SourceError as error:
                error.url = error.url or safe_url
                raise
            challenge = detect_challenge(response.status, response.headers, response.content)
            if challenge is None:
                self._level = level
                return response
            reason = challenge
            logger.info("%s: %s via %s", self.spec.source, challenge, fetcher.name)
        raise BlockedError(f"{reason} (tried {', '.join(tried)})", url=safe_url)

    def _should_retry(self, response: Response) -> bool:
        if response.status not in RETRY_STATUSES:
            return False
        return detect_challenge(response.status, response.headers, response.content) is None

    async def _attempt(self, fetcher: Fetcher, request: Request, safe_url: str) -> Response:
        """Send one request through a transport, retrying on 429, 5xx, and network errors."""
        host = urlsplit(request.url).hostname or ""
        limiter = self._resources.limiters.get(host, self._config.rate(self.spec.source))
        rng = self._resources.rng
        attempt = 0
        while True:
            await limiter.acquire()
            try:
                response = await fetcher.fetch(request)
            except TransportError as error:
                if attempt >= self._policy.retries:
                    raise
                delay = self._policy.backoff(attempt, rng)
                logger.debug("%s retry %s after %s", self.spec.source, safe_url, error)
            else:
                if attempt >= self._policy.retries or not self._should_retry(response):
                    return response
                retry_after = response.headers.get("retry-after")
                delay = self._policy.delay(attempt, retry_after, rng, self._resources.now())
                if delay > self._policy.max_wait:
                    raise RateLimitedError(f"asked to wait {delay:.0f} s", url=safe_url)
                logger.debug(
                    "%s retry %s after HTTP %s", self.spec.source, safe_url, response.status
                )
            await self._resources.sleep(delay)
            attempt += 1
