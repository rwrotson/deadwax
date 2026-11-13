import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from deadwax.core import (
    BlockedError,
    ConfigurationError,
    NotFoundError,
    RateLimitedError,
    SourceError,
)
from deadwax.sources import (
    CacheSettings,
    Escalation,
    HttpSettings,
    LastfmSettings,
    SourcesConfig,
)
from deadwax.sources._http import (
    ClientSpec,
    Fetcher,
    HostLimiters,
    HttpClient,
    HttpResources,
    Profile,
    Request,
    Response,
    ResponseCache,
    TransportError,
    escalation_steps,
    redact,
    route,
)
from deadwax.sources._http import client as client_module

NOW = datetime(2026, 11, 12, tzinfo=UTC)
URL = "https://api.example.org/record"
CHALLENGE = b"<html><title>Just a moment...</title></html>"


@dataclass
class FakeTime:
    now: float = 1000.0
    sleeps: list[float] = field(default_factory=list)

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class Server:
    """MockTransport handler answering with queued responses; the last one repeats."""

    answers: list[httpx.Response | Exception]
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


@dataclass
class FakeFetcher:
    name: str
    answers: list[Response | SourceError | ConfigurationError]
    requests: list[Request] = field(default_factory=list)
    closed: bool = False

    async def fetch(self, request: Request) -> Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def aclose(self) -> None:
        self.closed = True


def page(status: int = 200, content: bytes = b"<html>ok</html>") -> Response:
    return Response(url=URL, status=status, content=content)


@dataclass
class Setup:
    server: Server
    time: FakeTime = field(default_factory=FakeTime)
    cache: ResponseCache | None = None
    fetchers: dict[Escalation, FakeFetcher | ConfigurationError] = field(default_factory=dict)
    retries: int = 2
    blocked_ttl: float = 86400
    proxy: str | None = None
    created: list[Escalation] = field(default_factory=list)
    proxies: list[str | None] = field(default_factory=list)

    def client(
        self,
        profile: Profile = Profile.API,
        secret_params: frozenset[str] = frozenset(),
        escalation: Escalation | None = None,
    ) -> HttpClient:
        def factory(step: Escalation) -> Callable[[HttpSettings, str | None], Fetcher]:
            def create(settings: HttpSettings, proxy: str | None) -> Fetcher:
                self.created.append(step)
                self.proxies.append(proxy)
                fetcher = self.fetchers[step]
                if isinstance(fetcher, ConfigurationError):
                    raise fetcher
                return fetcher

            return create

        resources = HttpResources(
            limiters=HostLimiters(clock=self.time.clock, sleep=self.time.sleep),
            cache=self.cache,
            transport=httpx.MockTransport(self.server),
            escalations={step: factory(step) for step in Escalation},
            installed=lambda package: True,
            sleep=self.time.sleep,
            now=lambda: NOW,
            rng=random.Random(0),  # noqa: S311 -- seeded test jitter
        )
        config = SourcesConfig(
            http=HttpSettings(retries=self.retries, escalation=escalation, contact="https://c"),
            cache=CacheSettings(blocked_ttl=self.blocked_ttl),
            lastfm=LastfmSettings(proxy=SecretStr(self.proxy) if self.proxy else None),
        )
        spec = ClientSpec("lastfm", profile, {"x-source": "test"}, secret_params)
        return HttpClient(spec, config, resources)


@pytest.mark.asyncio
async def test_api_requests_are_honest_and_cached(tmp_path: Path) -> None:
    setup = Setup(Server([httpx.Response(200, json={"ok": True})]))
    setup.cache = ResponseCache(tmp_path / "cache.sqlite")

    async with setup.client() as client:
        first = await client.get(URL, params={"q": "missing"})
        second = await client.get(URL, params={"q": "missing"})
    setup.cache.close()

    [request] = setup.server.requests
    assert request.headers["user-agent"].startswith("deadwax/")
    assert request.headers["user-agent"].endswith("(+https://c)")
    assert request.headers["x-source"] == "test"
    assert first.json() == second.json() == {"ok": True}


@pytest.mark.asyncio
async def test_not_found_is_raised_and_cached(tmp_path: Path) -> None:
    setup = Setup(Server([httpx.Response(404)]))
    setup.cache = ResponseCache(tmp_path / "cache.sqlite")

    async with setup.client() as client:
        for _ in range(2):
            with pytest.raises(NotFoundError) as raised:
                await client.get(URL)
    setup.cache.close()

    assert raised.value.url == URL
    assert len(setup.server.requests) == 1


@pytest.mark.asyncio
async def test_retry_after_is_honoured(tmp_path: Path) -> None:
    server = Server(
        [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, text="ok")],
    )
    setup = Setup(server)
    setup.cache = ResponseCache(tmp_path / "cache.sqlite")

    async with setup.client() as client:
        response = await client.get(URL)
    setup.cache.close()

    assert response.text == "ok"
    assert 7.0 in setup.time.sleeps
    assert len(server.requests) == 2


@pytest.mark.asyncio
async def test_persistent_rate_limit_is_reported() -> None:
    setup = Setup(Server([httpx.Response(429)]))

    async with setup.client() as client:
        with pytest.raises(RateLimitedError, match="too many requests"):
            await client.get(URL)

    assert len(setup.server.requests) == 3


@pytest.mark.asyncio
async def test_too_long_retry_after_gives_up_at_once() -> None:
    setup = Setup(Server([httpx.Response(503, headers={"Retry-After": "3600"})]))

    async with setup.client() as client:
        with pytest.raises(RateLimitedError, match="asked to wait 3600 s"):
            await client.get(URL)

    assert len(setup.server.requests) == 1


@pytest.mark.asyncio
async def test_server_errors_are_retried_with_backoff() -> None:
    setup = Setup(Server([httpx.Response(502), httpx.Response(200, text="ok")]))

    async with setup.client() as client:
        response = await client.get(URL)

    assert response.text == "ok"
    assert any(0 <= wait <= 1.0 for wait in setup.time.sleeps)


@pytest.mark.asyncio
async def test_other_errors_are_not_retried() -> None:
    setup = Setup(Server([httpx.Response(400)]))

    async with setup.client() as client:
        with pytest.raises(SourceError, match="HTTP 400"):
            await client.get(URL)

    assert len(setup.server.requests) == 1


@pytest.mark.asyncio
async def test_network_errors_are_retried_then_raised_without_secrets() -> None:
    refused = httpx.ConnectError("refused")
    setup = Setup(Server([refused, httpx.Response(200, text="ok")]))
    failing = Setup(Server([refused]))

    async with setup.client() as client:
        recovered = await client.get(URL)
    async with failing.client(secret_params=frozenset({"api_key"})) as client:
        with pytest.raises(TransportError) as raised:
            await client.get(URL, params={"api_key": "s3cret", "q": "x"})

    assert recovered.text == "ok"
    assert len(failing.server.requests) == 3
    assert raised.value.url == f"{URL}?q=x"


@pytest.mark.asyncio
async def test_secret_parameters_are_sent_but_not_exposed() -> None:
    setup = Setup(Server([httpx.Response(200), httpx.Response(500)]))

    async with setup.client(secret_params=frozenset({"api_key"})) as client:
        response = await client.get(URL, params={"q": "x", "api_key": "s3cret"})
        with pytest.raises(SourceError) as raised:
            await client.request("POST", URL, params={"api_key": "s3cret"}, body=b"{}")

    assert setup.server.requests[0].url.params["api_key"] == "s3cret"
    assert response.url == f"{URL}?q=x"
    assert raised.value.url == URL


@pytest.mark.asyncio
async def test_browser_profile_escalates_and_stays_escalated() -> None:
    setup = Setup(Server([httpx.Response(403, content=CHALLENGE)]))
    impersonate = FakeFetcher("impersonate", [page()])
    setup.fetchers = {Escalation.IMPERSONATE: impersonate}

    client = setup.client(Profile.BROWSER, escalation=Escalation.IMPERSONATE)
    async with client:
        first = await client.get(URL)
        second = await client.get(URL)

    assert first.text == second.text == "<html>ok</html>"
    assert len(setup.server.requests) == 1
    assert len(impersonate.requests) == 2
    assert setup.server.requests[0].headers["user-agent"].startswith("Mozilla/5.0")
    assert impersonate.closed


@pytest.mark.asyncio
async def test_blocked_when_every_transport_meets_a_challenge() -> None:
    setup = Setup(Server([httpx.Response(503, content=CHALLENGE)]))
    setup.fetchers = {
        Escalation.IMPERSONATE: FakeFetcher("impersonate", [page(403, CHALLENGE)]),
        Escalation.BROWSER: FakeFetcher("browser", [page(200, CHALLENGE)]),
        Escalation.NODRIVER: FakeFetcher("nodriver", [page(200, CHALLENGE)]),
    }

    async with setup.client(Profile.BROWSER) as client:
        with pytest.raises(
            BlockedError,
            match=r"tried httpx, impersonate, browser, nodriver",
        ) as raised:
            await client.get(URL)

    assert raised.value.url == URL
    assert len(setup.server.requests) == 1


@pytest.mark.asyncio
async def test_escalated_transport_errors_carry_the_url() -> None:
    setup = Setup(Server([httpx.Response(403, content=CHALLENGE)]), retries=0)
    setup.fetchers = {Escalation.IMPERSONATE: FakeFetcher("impersonate", [SourceError("boom")])}

    async with setup.client(Profile.BROWSER, escalation=Escalation.IMPERSONATE) as client:
        with pytest.raises(SourceError, match="boom") as raised:
            await client.get(URL)

    assert raised.value.url == URL


@pytest.mark.asyncio
async def test_api_profile_never_escalates() -> None:
    setup = Setup(Server([httpx.Response(403, headers={"cf-mitigated": "challenge"})]))

    async with setup.client() as client:
        with pytest.raises(BlockedError, match=r"Cloudflare challenge \(tried httpx\)"):
            await client.get(URL)


MISSING = "Chromium for Playwright is not installed: run 'playwright install chromium'"


@pytest.mark.asyncio
async def test_an_unavailable_step_ends_the_ladder_as_blocked() -> None:
    setup = Setup(Server([httpx.Response(403, content=CHALLENGE)]))
    impersonate = FakeFetcher("impersonate", [page(403, CHALLENGE)])
    setup.fetchers = {
        Escalation.IMPERSONATE: impersonate,
        Escalation.BROWSER: ConfigurationError(MISSING),
    }

    async with setup.client(Profile.BROWSER) as client:
        for _ in range(2):
            with pytest.raises(BlockedError) as raised:
                await client.get(URL)

    assert str(raised.value) == (
        f"Cloudflare challenge (tried httpx, impersonate; browser unavailable: {MISSING})"
    )
    assert raised.value.url == URL
    assert setup.created == [Escalation.IMPERSONATE, Escalation.BROWSER]


@pytest.mark.asyncio
async def test_a_step_failing_on_first_use_is_dropped_and_closed() -> None:
    setup = Setup(Server([httpx.Response(403, content=CHALLENGE)]))
    browser = FakeFetcher("browser", [ConfigurationError(MISSING)])
    setup.fetchers = {
        Escalation.IMPERSONATE: FakeFetcher("impersonate", [page(403, CHALLENGE)]),
        Escalation.BROWSER: browser,
    }

    async with setup.client(Profile.BROWSER) as client:
        with pytest.raises(BlockedError, match="tried httpx, impersonate; browser unavailable"):
            await client.get(URL)
        with pytest.raises(BlockedError, match="tried httpx, impersonate; browser unavailable"):
            await client.get(URL)

    assert browser.closed
    assert len(browser.requests) == 1


@pytest.mark.asyncio
async def test_an_explicitly_chosen_step_that_cannot_run_is_a_configuration_error() -> None:
    setup = Setup(Server([httpx.Response(403, content=CHALLENGE)]))
    setup.fetchers = {
        Escalation.IMPERSONATE: FakeFetcher("impersonate", [page(403, CHALLENGE)]),
        Escalation.BROWSER: ConfigurationError(MISSING),
    }

    async with setup.client(Profile.BROWSER, escalation=Escalation.BROWSER) as client:
        with pytest.raises(ConfigurationError, match="playwright install chromium"):
            await client.get(URL)


@pytest.mark.asyncio
async def test_blocked_pages_are_cached_for_blocked_ttl(tmp_path: Path) -> None:
    setup = Setup(Server([httpx.Response(403, headers={"cf-mitigated": "challenge"})]))
    setup.cache = ResponseCache(tmp_path / "cache.sqlite", clock=setup.time.clock)

    async with setup.client() as client:
        with pytest.raises(BlockedError, match=r"\(tried httpx\)$"):
            await client.get(URL)
        with pytest.raises(BlockedError, match=r"\(tried httpx\) \(cached\)$") as cached:
            await client.get(URL)
        setup.time.now += 86401
        with pytest.raises(BlockedError, match=r"\(tried httpx\)$"):
            await client.get(URL)
    setup.cache.close()

    assert cached.value.url == URL
    assert len(setup.server.requests) == 2


@pytest.mark.asyncio
async def test_a_block_on_another_route_is_not_reused(tmp_path: Path) -> None:
    setup = Setup(Server([httpx.Response(403, headers={"cf-mitigated": "challenge"})]))
    setup.cache = ResponseCache(tmp_path / "cache.sqlite", clock=setup.time.clock)

    async with setup.client() as client:
        with pytest.raises(BlockedError, match=r"\(tried httpx\)$"):
            await client.get(URL)
    setup.proxy = "direct"
    async with setup.client() as client:
        with pytest.raises(BlockedError, match=r"\(tried httpx\)$"):
            await client.get(URL)
        with pytest.raises(BlockedError, match=r"\(cached\)$"):
            await client.get(URL)
    setup.cache.close()

    assert len(setup.server.requests) == 2


@pytest.mark.asyncio
async def test_escalation_steps_use_the_source_proxy() -> None:
    setup = Setup(Server([httpx.Response(403, content=CHALLENGE)]))
    setup.fetchers = {Escalation.IMPERSONATE: FakeFetcher("impersonate", [page()])}
    setup.proxy = "http://user:secret@proxy.example:8080"

    async with setup.client(Profile.BROWSER, escalation=Escalation.IMPERSONATE) as client:
        await client.get(URL)

    assert setup.proxies == ["http://user:secret@proxy.example:8080"]


@pytest.mark.parametrize(
    ("proxy", "expected"),
    [
        (None, "environment"),
        ("direct", "direct"),
        ("http://user:secret@proxy.example:8080", "http://proxy.example:8080"),
    ],
)
def test_route_names_the_proxy_without_credentials(proxy: str | None, expected: str) -> None:
    assert route(proxy) == expected


@pytest.mark.asyncio
async def test_blocked_pages_are_not_cached_with_zero_ttl(tmp_path: Path) -> None:
    setup = Setup(Server([httpx.Response(403, headers={"cf-mitigated": "challenge"})]))
    setup.cache = ResponseCache(tmp_path / "cache.sqlite")
    setup.blocked_ttl = 0

    async with setup.client() as client:
        for _ in range(2):
            with pytest.raises(BlockedError, match=r"\(tried httpx\)$"):
                await client.get(URL)
    setup.cache.close()

    assert len(setup.server.requests) == 2


@pytest.mark.parametrize(
    ("setting", "installed", "expected"),
    [
        (None, set(), []),
        (None, {"curl_cffi"}, [Escalation.IMPERSONATE]),
        (None, {"patchright"}, [Escalation.BROWSER]),
        (None, {"nodriver"}, [Escalation.NODRIVER]),
        (
            None,
            {"curl_cffi", "patchright", "nodriver"},
            [Escalation.IMPERSONATE, Escalation.BROWSER, Escalation.NODRIVER],
        ),
        (Escalation.NONE, {"curl_cffi", "patchright"}, []),
        (Escalation.IMPERSONATE, set(), [Escalation.IMPERSONATE]),
        (Escalation.IMPERSONATE, {"patchright"}, [Escalation.IMPERSONATE]),
        (Escalation.BROWSER, set(), [Escalation.BROWSER]),
        (Escalation.BROWSER, {"curl_cffi"}, [Escalation.IMPERSONATE, Escalation.BROWSER]),
        (Escalation.PATCHRIGHT, {"curl_cffi"}, [Escalation.IMPERSONATE, Escalation.BROWSER]),
        (
            Escalation.NODRIVER,
            {"curl_cffi", "patchright"},
            [Escalation.IMPERSONATE, Escalation.BROWSER, Escalation.NODRIVER],
        ),
    ],
)
def test_escalation_steps(
    setting: Escalation | None,
    installed: set[str],
    expected: list[Escalation],
) -> None:
    assert escalation_steps(setting, installed.__contains__) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x/a?q=1", "https://x/a?q=1"),
        ("https://x/a?q=1&token=t", "https://x/a?q=1"),
        ("https://x/a?token=t", "https://x/a"),
    ],
)
def test_redact(url: str, expected: str) -> None:
    assert redact(url, {"token"}) == expected
    assert redact(url, set()) == url


def test_default_resources() -> None:
    resources = HttpResources()

    assert resources.cache is None
    assert set(resources.escalations) == {
        Escalation.IMPERSONATE,
        Escalation.BROWSER,
        Escalation.NODRIVER,
    }
    assert resources.now().tzinfo is UTC
    assert client_module._installed("json")
    assert not client_module._installed("deadwax_missing_package")


type Traced = Callable[[str], list[dict[str, object]]]


@pytest.mark.asyncio
async def test_requests_are_traced_with_cache_state_and_body_digest(
    tmp_path: Path,
    traced: Traced,
) -> None:
    setup = Setup(Server([httpx.Response(200, text="ok")]))
    setup.cache = ResponseCache(tmp_path / "cache.sqlite")

    async with setup.client(secret_params=frozenset({"key"})) as client:
        await client.get(URL, params={"q": "a", "key": "secret"})
        await client.get(URL, params={"q": "a", "key": "secret"})
    setup.cache.close()

    miss, hit = traced("http.request")
    assert miss["url"] == f"{URL}?q=a"
    assert (miss["cache"], miss["status"], miss["attempts"]) == ("miss", 200, 1)
    assert miss["fetchers"] == ["httpx"]
    assert miss["bytes"] == 2
    assert miss["sha256"] == "2689367b205c16ce32ed4200942b8b8b1e262dfc70d9bc9fbc77c49699a4f1df"
    assert (hit["cache"], hit["attempts"], hit["sha256"]) == ("hit", 0, miss["sha256"])


@pytest.mark.asyncio
async def test_failed_requests_and_retries_are_traced(traced: Traced) -> None:
    setup = Setup(Server([httpx.Response(503), httpx.Response(404)]))

    async with setup.client() as client:
        with pytest.raises(NotFoundError):
            await client.get(URL)

    [retry] = traced("http.retry")
    assert retry["status"] == 503
    [request] = traced("http.request")
    assert (request["cache"], request["status"], request["attempts"]) == ("off", 404, 2)


@pytest.mark.asyncio
async def test_transport_failures_are_traced_as_errors(traced: Traced) -> None:
    setup = Setup(Server([httpx.ConnectError("refused")]), retries=0)

    async with setup.client() as client:
        with pytest.raises(TransportError):
            await client.get(URL)

    [request] = traced("http.request")
    assert "status" not in request
    assert request["error"] == {"type": "TransportError", "message": "ConnectError: refused"}
