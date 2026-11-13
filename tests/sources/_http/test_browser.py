import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, field

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
from deadwax.sources._http import client as client_module


class FakeError(Exception):
    pass


@dataclass
class Scenario:
    """What the fake browser does; tests change it before fetching."""

    html: str = "<html>page</html>"
    statuses: list[int] = field(default_factory=lambda: [403, 200])
    launch_fails: bool = False
    goto_fails: bool = False
    never_idle: bool = False
    launches: list[dict[str, object]] = field(default_factory=list)
    contexts: list[dict[str, object]] = field(default_factory=list)
    pages: list[FakePage] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)


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

    async def wait_for_load_state(self, state: str, **options: object) -> None:
        if self.scenario.never_idle:
            raise FakeError("Timeout")

    async def content(self) -> str:
        return self.scenario.html

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
        self.scenario.launches.append(options)
        if self.scenario.launch_fails:
            raise FakeError("Executable doesn't exist")
        return FakeBrowser(self.scenario)


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

    api = types.ModuleType("playwright.async_api")
    api.Error = FakeError  # type: ignore[attr-defined]
    api.async_playwright = Manager  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", api)
    return state


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
async def test_page_without_navigation_counts_as_ok(scenario: Scenario) -> None:
    scenario.statuses = []
    fetcher = BrowserFetcher(timeout=5, max_bytes=100)

    response = await fetcher.fetch(PAGE)

    assert response.status == 200
    assert response.headers == {}


@pytest.mark.asyncio
async def test_navigation_errors_and_size_limit(scenario: Scenario) -> None:
    fetcher = BrowserFetcher(timeout=5, max_bytes=5)

    with pytest.raises(ResponseTooLargeError):
        await fetcher.fetch(PAGE)
    scenario.goto_fails = True
    with pytest.raises(TransportError, match="ERR_CONNECTION_RESET"):
        await fetcher.fetch(PAGE)
    with pytest.raises(SourceError, match="cannot send POST"):
        await fetcher.fetch(Request("POST", "https://x"))

    assert all(page.closed for page in scenario.pages)


@pytest.mark.asyncio
async def test_missing_chromium_is_a_configuration_error(scenario: Scenario) -> None:
    scenario.launch_fails = True
    fetcher = client_module._browser(HttpSettings(), None)

    with pytest.raises(ConfigurationError, match="playwright install chromium"):
        await fetcher.fetch(PAGE)

    assert scenario.closed == ["playwright"]


def test_missing_extra_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "playwright", None)

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
