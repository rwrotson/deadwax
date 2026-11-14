from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from deadwax.core import ConfigurationError
from deadwax.sources._http import NodriverFetcher, Request, TransportError
from deadwax.sources._http import nodriver as nodriver_module


@dataclass
class FakeTab:
    """Record navigation and emit the final document response."""

    status: int | None = 200
    url: str = "about:blank"
    content: str = "<html>ready</html>"
    navigation_status: int = 200
    callback: Callable[[object], None] | None = None
    closed: bool = False

    def add_handler(self, event: object, callback: Callable[[object], None]) -> None:
        self.callback = callback

    async def get(self, url: str) -> None:
        self.url = url
        if self.status is not None and self.callback is not None:
            self.callback(
                SimpleNamespace(
                    type_=SimpleNamespace(value="Document"),
                    response=SimpleNamespace(
                        url=url,
                        status=self.status,
                        headers={"Content-Type": "text/html"},
                    ),
                ),
            )

    async def send(self, command: object) -> None:
        pass

    async def evaluate(self, expression: str, *, return_by_value: bool) -> int:
        return self.navigation_status

    async def sleep(self, seconds: float) -> None:
        pass

    async def get_content(self) -> str:
        return self.content

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeBrowser:
    """Provide a new tab and track shutdown."""

    tab: FakeTab
    stopped: bool = False

    async def get(self, url: str, *, new_tab: bool) -> FakeTab:
        return self.tab

    def stop(self) -> None:
        self.stopped = True


@dataclass
class Scenario:
    """Hold fake browser objects and launch arguments."""

    tab: FakeTab = field(default_factory=FakeTab)
    launched: list[dict[str, object]] = field(default_factory=list)
    browser: FakeBrowser | None = None


@pytest.fixture
def scenario(monkeypatch: pytest.MonkeyPatch) -> Scenario:
    state = Scenario()

    async def start(**kwargs: object) -> FakeBrowser:
        state.launched.append(kwargs)
        state.browser = FakeBrowser(state.tab)
        return state.browser

    network = SimpleNamespace(ResponseReceived=object)
    network.enable = object
    module = SimpleNamespace(start=start, cdp=SimpleNamespace(network=network))
    monkeypatch.setattr(nodriver_module, "_module", lambda: module)
    return state


@pytest.mark.asyncio
async def test_fetch_returns_final_document(scenario: Scenario) -> None:
    fetcher = NodriverFetcher(timeout=5, max_bytes=100, proxy="http://proxy.test:8080")

    response = await fetcher.fetch(Request("GET", "https://example.test/page"))
    await fetcher.aclose()

    assert response.status == 200
    assert response.headers == {"content-type": "text/html"}
    assert response.text == "<html>ready</html>"
    assert scenario.launched == [
        {"headless": True, "browser_args": ["--proxy-server=http://proxy.test:8080"]},
    ]
    assert scenario.tab.closed
    assert scenario.browser is not None
    assert scenario.browser.stopped


@pytest.mark.asyncio
async def test_rendered_page_without_document_event_is_returned(scenario: Scenario) -> None:
    scenario.tab.status = None
    fetcher = NodriverFetcher(timeout=5, max_bytes=100)

    response = await fetcher.fetch(Request("GET", "https://example.test/page"))

    assert response.status == 200
    assert response.text == "<html>ready</html>"
    assert scenario.tab.closed


@pytest.mark.asyncio
async def test_navigation_status_without_document_event_is_returned(scenario: Scenario) -> None:
    scenario.tab.status = None
    scenario.tab.navigation_status = 403
    fetcher = NodriverFetcher(timeout=5, max_bytes=100)

    response = await fetcher.fetch(Request("GET", "https://example.test/page"))

    assert response.status == 403


@pytest.mark.asyncio
async def test_empty_page_without_document_event_fails(scenario: Scenario) -> None:
    scenario.tab.status = None
    scenario.tab.content = ""
    fetcher = NodriverFetcher(timeout=5, max_bytes=100)

    with pytest.raises(TransportError, match="did not load a document"):
        await fetcher.fetch(Request("GET", "https://example.test/page"))

    assert scenario.tab.closed


@pytest.mark.asyncio
async def test_authenticated_proxy_is_rejected(scenario: Scenario) -> None:
    fetcher = NodriverFetcher(
        timeout=5,
        max_bytes=100,
        proxy="http://user:password@proxy.test:8080",
    )

    with pytest.raises(ConfigurationError, match="authenticated HTTP proxy"):
        await fetcher.fetch(Request("GET", "https://example.test/page"))

    assert scenario.launched == []
