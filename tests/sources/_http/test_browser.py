import asyncio
import logging
import sys
import types
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from deadwax.core import ConfigurationError, SourceError
from deadwax.sources import HttpSettings
from deadwax.sources._http import (
    CHROME,
    BrowserFetcher,
    Request,
    ResponseTooLargeError,
    TransportError,
    launch_proxy,
)
from deadwax.sources._http import browser as browser_module
from deadwax.sources._http import client as client_module


class FakeError(Exception):
    pass


@dataclass
class Scenario:
    """What the fake browser does; tests change it before fetching."""

    html: str = "<html>page</html>"
    html_sequence: list[str] = field(default_factory=list)
    statuses: list[int] = field(default_factory=lambda: [403, 200])
    launch_fails: bool = False
    launch_error: str = "Executable doesn't exist"
    close_fails: bool = False
    goto_fails: bool = False
    goto_error: str | None = None
    never_idle: bool = False
    launches: list[dict[str, object]] = field(default_factory=list)
    contexts: list[dict[str, object]] = field(default_factory=list)
    pages: list[FakePage] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    fronts: list[FakePage] = field(default_factory=list)


@dataclass
class FakeRequest:
    navigation: bool

    def is_navigation_request(self) -> bool:
        return self.navigation


@dataclass
class FakeResponse:
    status: int
    request: FakeRequest
    frame: object

    async def all_headers(self) -> dict[str, str]:
        return {"content-type": "text/html", "x-status": str(self.status)}


class FakePage:
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.main_frame = object()
        self.handlers: list[Callable[[FakeResponse], None]] = []
        self.url = "about:blank"
        self.closed = False

    def on(self, event: str, handler: Callable[[FakeResponse], None]) -> None:
        self.handlers.append(handler)

    async def goto(self, url: str, **options: object) -> None:
        if self.scenario.goto_fails:
            raise FakeError("net::ERR_CONNECTION_RESET")
        self.url = url
        responses = [
            FakeResponse(s, FakeRequest(navigation=True), self.main_frame)
            for s in self.scenario.statuses
        ]
        responses.insert(1, FakeResponse(200, FakeRequest(navigation=False), self.main_frame))
        responses.append(FakeResponse(500, FakeRequest(navigation=True), object()))
        for response in responses:
            for handler in self.handlers:
                handler(response)
        if self.scenario.goto_error is not None:
            raise FakeError(self.scenario.goto_error)

    async def wait_for_load_state(self, state: str, **options: object) -> None:
        if self.scenario.never_idle:
            raise FakeError("Timeout")

    async def bring_to_front(self) -> None:
        self.scenario.fronts.append(self)

    async def content(self) -> str:
        if self.scenario.html_sequence:
            return self.scenario.html_sequence.pop(0)
        return self.scenario.html

    async def evaluate(self, script: str, arguments: dict[str, object]) -> dict[str, object]:
        return {
            "url": arguments["url"],
            "status": 200,
            "content": '{"results": 1}',
            "headers": {"content-type": "application/json"},
        }

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeContext:
    scenario: Scenario

    async def new_page(self) -> FakePage:
        page = FakePage(self.scenario)
        self.scenario.pages.append(page)
        return page

    async def close(self) -> None:
        self.scenario.closed.append("context")
        if self.scenario.close_fails:
            raise FakeError("driver connection closed")


@dataclass
class FakeBrowser:
    scenario: Scenario

    async def new_context(self, **kwargs: object) -> FakeContext:
        self.scenario.contexts.append(kwargs)
        return FakeContext(self.scenario)

    async def close(self) -> None:
        self.scenario.closed.append("browser")


@dataclass
class FakeChromium:
    scenario: Scenario

    async def launch(self, **options: object) -> FakeBrowser:
        await asyncio.sleep(0)
        self.scenario.launches.append(options)
        if self.scenario.launch_fails:
            raise FakeError(self.scenario.launch_error)
        return FakeBrowser(self.scenario)

    async def launch_persistent_context(self, **options: object) -> FakeContext:
        self.scenario.launches.append(options)
        return FakeContext(self.scenario)


@dataclass
class FakePlaywright:
    scenario: Scenario

    @property
    def chromium(self) -> FakeChromium:
        return FakeChromium(self.scenario)

    async def stop(self) -> None:
        self.scenario.closed.append("playwright")


@pytest.fixture
def scenario(monkeypatch: pytest.MonkeyPatch) -> Scenario:
    state = Scenario()

    class Manager:
        async def start(self) -> FakePlaywright:
            return FakePlaywright(state)

    api = types.ModuleType("patchright.async_api")
    api.Error = FakeError  # type: ignore[attr-defined]
    api.async_playwright = Manager  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "patchright", types.ModuleType("patchright"))
    monkeypatch.setitem(sys.modules, "patchright.async_api", api)
    return state


CHALLENGE = "<html><title>Just a moment...</title></html>"
PAGE = Request("GET", "https://www.discogs.com/release/1-reviews", (("page", "2"),))


@pytest.mark.asyncio
async def test_page_status_is_the_last_main_navigation(scenario: Scenario) -> None:
    fetcher = BrowserFetcher(timeout=5, max_bytes=100)

    first = await fetcher.fetch(PAGE)
    scenario.never_idle = True
    second = await fetcher.fetch(PAGE)
    await fetcher.aclose()
    await fetcher.aclose()

    assert first.status == second.status == 200
    assert first.url == "https://www.discogs.com/release/1-reviews?page=2"
    assert first.text == "<html>page</html>"
    assert first.headers["x-status"] == "200"
    assert len(scenario.contexts) == 1
    assert scenario.contexts[0]["user_agent"] == CHROME.user_agent
    assert scenario.contexts[0]["extra_http_headers"] == {"accept-language": "en-US,en;q=0.9"}
    assert all(page.closed for page in scenario.pages)
    assert scenario.closed == ["context", "browser", "playwright"]


@pytest.mark.asyncio
async def test_page_without_navigation_fails(scenario: Scenario) -> None:
    scenario.statuses = []
    fetcher = BrowserFetcher(timeout=5, max_bytes=100)

    with pytest.raises(TransportError, match="did not receive a document response"):
        await fetcher.fetch(PAGE)


@pytest.mark.asyncio
async def test_navigation_errors_and_size_limit(scenario: Scenario) -> None:
    fetcher = BrowserFetcher(timeout=5, max_bytes=5)

    with pytest.raises(ResponseTooLargeError):
        await fetcher.fetch(PAGE)
    scenario.goto_fails = True
    with pytest.raises(TransportError, match="ERR_CONNECTION_RESET"):
        await fetcher.fetch(PAGE)
    with pytest.raises(SourceError, match="cannot send PUT"):
        await fetcher.fetch(Request("PUT", "https://x"))

    assert all(page.closed for page in scenario.pages)


@pytest.mark.asyncio
async def test_post_uses_browser_page_and_returns_api_response(scenario: Scenario) -> None:
    fetcher = BrowserFetcher(timeout=5, max_bytes=100)

    response = await fetcher.fetch(
        Request("POST", "https://example.com/search", body=b"id=0"),
    )

    assert response.status == 200
    assert response.json() == {"results": 1}
    assert scenario.pages[0].closed


@pytest.mark.asyncio
async def test_missing_chromium_is_a_configuration_error(scenario: Scenario) -> None:
    scenario.launch_fails = True
    fetcher = client_module._browser(HttpSettings(), None)

    with pytest.raises(ConfigurationError, match="patchright install chromium"):
        await fetcher.fetch(PAGE)

    assert scenario.closed == ["playwright"]


def test_missing_extra_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "patchright", None)

    with pytest.raises(ConfigurationError, match=r"deadwax\[browser\]"):
        BrowserFetcher(timeout=5, max_bytes=5)


@pytest.mark.asyncio
async def test_chromium_is_launched_with_the_proxy(scenario: Scenario) -> None:
    fetcher = client_module._browser(HttpSettings(), "http://proxy.example:8080")

    await fetcher.fetch(PAGE)
    await fetcher.aclose()

    assert scenario.launches == [
        {"headless": True, "proxy": {"server": "http://proxy.example:8080"}},
    ]


@pytest.mark.asyncio
async def test_chrome_uses_a_temporary_profile_without_identity_overrides(
    scenario: Scenario,
) -> None:
    fetcher = BrowserFetcher(timeout=5, max_bytes=100, headless=False, channel="chrome")

    await fetcher.fetch(PAGE)
    profile = scenario.launches[0]["user_data_dir"]
    await fetcher.aclose()

    assert scenario.launches[0]["channel"] == "chrome"
    assert scenario.launches[0]["headless"] is False
    assert scenario.launches[0]["no_viewport"] is True
    assert scenario.contexts == []
    assert scenario.closed == ["context", "playwright"]
    assert isinstance(profile, str)
    assert not await asyncio.to_thread(Path(profile).exists)


@pytest.mark.asyncio
async def test_chrome_retains_an_explicit_profile(scenario: Scenario, tmp_path: Path) -> None:
    profile = tmp_path / "browser-profile"
    fetcher = BrowserFetcher(
        timeout=5,
        max_bytes=100,
        channel="chrome",
        profile_dir=profile,
    )

    await fetcher.fetch(PAGE)
    await fetcher.aclose()

    assert scenario.launches[0]["user_data_dir"] == str(profile)
    assert fetcher._profile is None


@pytest.mark.asyncio
async def test_browser_waits_for_required_page_state(scenario: Scenario) -> None:
    scenario.html_sequence = ["<html>loading</html>", "<html>READY</html>"]
    fetcher = BrowserFetcher(timeout=5, max_bytes=100, challenge_wait=1)

    response = await fetcher.fetch(
        Request("GET", PAGE.url, required_marker=b"READY"),
    )

    assert response.text == "<html>READY</html>"


@pytest.mark.asyncio
async def test_browser_waits_for_aws_waf_page_to_clear(scenario: Scenario) -> None:
    scenario.html_sequence = [
        "<script>window.awsWafCookieDomainList = [];</script>",
        "<html>ready</html>",
    ]
    fetcher = BrowserFetcher(timeout=5, max_bytes=100, challenge_wait=1)

    response = await fetcher.fetch(PAGE)

    assert response.text == "<html>ready</html>"


@pytest.mark.asyncio
async def test_driver_close_error_does_not_mask_navigation_error(scenario: Scenario) -> None:
    scenario.goto_fails = True
    scenario.close_fails = True
    fetcher = BrowserFetcher(timeout=5, max_bytes=100, channel="chrome")

    with pytest.raises(TransportError, match="ERR_CONNECTION_RESET"):
        await fetcher.fetch(PAGE)
    await fetcher.aclose()

    assert scenario.closed == ["context", "playwright"]


@pytest.mark.asyncio
async def test_browser_returns_incomplete_page_when_wait_expires(scenario: Scenario) -> None:
    fetcher = BrowserFetcher(timeout=5, max_bytes=100, challenge_wait=0)

    response = await fetcher.fetch(Request("GET", PAGE.url, required_marker=b"MISSING"))

    assert b"MISSING" not in response.content


@pytest.mark.parametrize(
    ("proxy", "expected"),
    [
        (None, {}),
        ("direct", {"args": ["--no-proxy-server"]}),
        ("http://proxy.example:8080", {"proxy": {"server": "http://proxy.example:8080"}}),
        (
            "https://us%40r:p%3Ass@[::1]:3128",
            {"proxy": {"server": "https://[::1]:3128", "username": "us@r", "password": "p:ss"}},
        ),
    ],
)
def test_launch_proxy(proxy: str | None, expected: dict[str, object]) -> None:
    assert launch_proxy(proxy) == expected


@pytest.mark.asyncio
async def test_concurrent_first_fetches_launch_one_browser(scenario: Scenario) -> None:
    fetcher = BrowserFetcher(timeout=5, max_bytes=100)

    await asyncio.gather(fetcher.fetch(PAGE), fetcher.fetch(PAGE))

    assert len(scenario.launches) == 1
    assert len(scenario.pages) == 2


@pytest.mark.asyncio
async def test_other_launch_failures_are_transport_errors(scenario: Scenario) -> None:
    scenario.launch_fails = True
    scenario.launch_error = "ProcessSingleton: the profile is already in use"
    fetcher = BrowserFetcher(timeout=5, max_bytes=100)

    with pytest.raises(TransportError, match="browser launch failed: ProcessSingleton"):
        await fetcher.fetch(PAGE)


@pytest.mark.asyncio
async def test_visible_browser_brings_a_challenge_to_the_front(
    scenario: Scenario,
    caplog: pytest.LogCaptureFixture,
) -> None:
    scenario.html_sequence = [CHALLENGE, CHALLENGE, "<html>solved</html>"]
    fetcher = BrowserFetcher(
        timeout=5,
        max_bytes=100,
        headless=False,
        challenge_wait=0,
        manual_challenge_wait=1,
    )

    with caplog.at_level(logging.WARNING, logger="deadwax.sources._http.browser"):
        response = await fetcher.fetch(PAGE)

    assert response.text == "<html>solved</html>"
    assert scenario.fronts == scenario.pages
    assert "solve the challenge in the browser window" in caplog.text


@pytest.mark.asyncio
async def test_challenged_pages_take_the_front_one_at_a_time(scenario: Scenario) -> None:
    scenario.html = CHALLENGE
    fetcher = BrowserFetcher(
        timeout=5,
        max_bytes=100,
        headless=False,
        challenge_wait=0,
        manual_challenge_wait=0.05,
    )
    started = asyncio.get_running_loop().time()

    await asyncio.gather(fetcher.fetch(PAGE), fetcher.fetch(PAGE))

    assert len(scenario.fronts) == 2
    assert asyncio.get_running_loop().time() - started >= 0.1


@pytest.mark.asyncio
async def test_headless_browser_does_not_ask_for_help(scenario: Scenario) -> None:
    scenario.html = CHALLENGE
    fetcher = BrowserFetcher(timeout=5, max_bytes=100, challenge_wait=0)

    response = await fetcher.fetch(PAGE)

    assert response.text == CHALLENGE
    assert scenario.fronts == []


@pytest.mark.asyncio
async def test_an_error_status_without_a_page_is_returned(scenario: Scenario) -> None:
    scenario.statuses = [403]
    scenario.goto_error = "net::ERR_HTTP_RESPONSE_CODE_FAILURE at https://rateyourmusic.com/"
    fetcher = BrowserFetcher(timeout=5, max_bytes=100)

    response = await fetcher.fetch(PAGE)

    assert response.status == 403
    assert response.content == b""
    assert scenario.pages[0].closed


@pytest.mark.asyncio
async def test_other_navigation_errors_stay_transport_errors(scenario: Scenario) -> None:
    scenario.goto_error = "net::ERR_NAME_NOT_RESOLVED"
    fetcher = BrowserFetcher(timeout=5, max_bytes=100)

    with pytest.raises(TransportError, match="ERR_NAME_NOT_RESOLVED"):
        await fetcher.fetch(PAGE)


@pytest.mark.asyncio
async def test_only_the_launch_is_kept_out_of_the_adapter_timeout(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pauses: list[str] = []

    @asynccontextmanager
    async def pause() -> AsyncIterator[None]:
        pauses.append("paused")
        yield

    monkeypatch.setattr(browser_module, "pause_adapter_timeout", pause)
    fetcher = BrowserFetcher(timeout=5, max_bytes=100)

    await fetcher.fetch(PAGE)
    await fetcher.fetch(PAGE)

    assert pauses == ["paused"]
    assert len(scenario.launches) == 1
