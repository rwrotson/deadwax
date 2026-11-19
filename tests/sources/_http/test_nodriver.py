import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
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
    content_sequence: list[str] = field(default_factory=list)
    navigation_status: int = 200
    callback: Callable[[object], None] | None = None
    closed: bool = False
    fronts: int = 0

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

    async def bring_to_front(self) -> None:
        self.fronts += 1

    async def evaluate(self, expression: str, *, return_by_value: bool) -> int:
        return self.navigation_status

    async def sleep(self, seconds: float) -> None:
        pass

    async def get_content(self) -> str:
        if self.content_sequence:
            return self.content_sequence.pop(0)
        return self.content

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeProcess:
    """Record whether shutdown waited for the subprocess."""

    waited: bool = False

    async def wait(self) -> int:
        self.waited = True
        return 0


@dataclass
class FakeBrowser:
    """Provide a new tab and track shutdown."""

    tab: FakeTab
    stopped: bool = False
    closed: bool = False
    _process: FakeProcess = field(default_factory=FakeProcess)

    async def get(self, url: str, *, new_tab: bool) -> FakeTab:
        return self.tab

    def stop(self) -> None:
        self.stopped = True

    async def aclose(self) -> None:
        self.closed = True


@dataclass
class Scenario:
    """Hold fake browser objects and launch arguments."""

    tab: FakeTab = field(default_factory=FakeTab)
    launched: list[dict[str, object]] = field(default_factory=list)
    browser: FakeBrowser | None = None
    launch_error: Exception | None = None


@pytest.fixture
def scenario(monkeypatch: pytest.MonkeyPatch) -> Scenario:
    state = Scenario()

    async def start(**kwargs: object) -> FakeBrowser:
        await asyncio.sleep(0)
        if state.launch_error is not None:
            raise state.launch_error
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
    assert scenario.browser.closed
    assert scenario.browser._process.waited


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
async def test_chrome_network_error_is_not_a_success(scenario: Scenario) -> None:
    scenario.tab.status = None
    scenario.tab.content = '<html><body class="neterror">ERR_INVALID_HANDLE</body></html>'
    fetcher = NodriverFetcher(timeout=5, max_bytes=100)

    with pytest.raises(TransportError, match="Chrome could not load"):
        await fetcher.fetch(Request("GET", "https://example.test/page"))


@pytest.mark.asyncio
async def test_explicit_browser_and_sandbox_settings(scenario: Scenario) -> None:
    fetcher = NodriverFetcher(
        timeout=5,
        max_bytes=100,
        browser_path=Path("/custom/chrome"),
        sandbox=False,
    )

    await fetcher.fetch(Request("GET", "https://example.test/page"))

    assert scenario.launched == [
        {
            "headless": True,
            "browser_args": [],
            "browser_executable_path": "/custom/chrome",
            "sandbox": False,
        },
    ]


@pytest.mark.asyncio
async def test_explicit_profile_is_passed_to_nodriver(scenario: Scenario, tmp_path: Path) -> None:
    profile = tmp_path / "nodriver-profile"
    fetcher = NodriverFetcher(timeout=5, max_bytes=100, profile_dir=profile)

    await fetcher.fetch(Request("GET", "https://example.test/page"))
    await fetcher.aclose()

    assert scenario.launched[0]["user_data_dir"] == str(profile)


@pytest.mark.asyncio
async def test_waits_for_required_page_state(scenario: Scenario) -> None:
    scenario.tab.content_sequence = ["<html>loading</html>", "<html>READY</html>"]
    fetcher = NodriverFetcher(timeout=5, max_bytes=100, challenge_wait=1)

    response = await fetcher.fetch(
        Request("GET", "https://example.test/page", required_marker=b"READY"),
    )

    assert response.text == "<html>READY</html>"


@pytest.mark.asyncio
async def test_returns_incomplete_page_when_wait_expires(scenario: Scenario) -> None:
    fetcher = NodriverFetcher(timeout=5, max_bytes=100, challenge_wait=0)

    response = await fetcher.fetch(
        Request("GET", "https://example.test/page", required_marker=b"MISSING"),
    )

    assert b"MISSING" not in response.content


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


@pytest.mark.asyncio
async def test_concurrent_first_fetches_launch_one_browser(scenario: Scenario) -> None:
    fetcher = NodriverFetcher(timeout=5, max_bytes=100)
    request = Request("GET", "https://example.test/page")

    await asyncio.gather(fetcher.fetch(request), fetcher.fetch(request))

    assert len(scenario.launched) == 1


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (FileNotFoundError("could not determine browser executable"), ConfigurationError),
        (RuntimeError("profile is already in use"), TransportError),
    ],
)
@pytest.mark.asyncio
async def test_launch_failures(
    scenario: Scenario,
    error: Exception,
    expected: type[Exception],
) -> None:
    scenario.launch_error = error
    fetcher = NodriverFetcher(timeout=5, max_bytes=100)

    with pytest.raises(expected):
        await fetcher.fetch(Request("GET", "https://example.test/page"))


@pytest.mark.asyncio
async def test_visible_browser_brings_a_challenge_to_the_front(
    scenario: Scenario,
    caplog: pytest.LogCaptureFixture,
) -> None:
    challenge = "<html><title>Just a moment...</title></html>"
    scenario.tab.content_sequence = [challenge, challenge, "<html>solved</html>"]
    fetcher = NodriverFetcher(
        timeout=5,
        max_bytes=100,
        headless=False,
        challenge_wait=0,
        manual_challenge_wait=1,
    )

    with caplog.at_level(logging.WARNING, logger="deadwax.sources._http.nodriver"):
        response = await fetcher.fetch(Request("GET", "https://example.test/page"))

    assert response.text == "<html>solved</html>"
    assert scenario.tab.fronts == 1
    assert "solve the challenge in the browser window" in caplog.text


@pytest.mark.asyncio
async def test_visible_browser_returns_a_page_missing_only_its_marker(scenario: Scenario) -> None:
    fetcher = NodriverFetcher(timeout=5, max_bytes=100, headless=False, challenge_wait=0)

    response = await fetcher.fetch(
        Request("GET", "https://example.test/page", required_marker=b"MISSING"),
    )

    assert b"MISSING" not in response.content
    assert scenario.tab.fronts == 0


@pytest.mark.asyncio
async def test_an_error_status_without_a_page_is_returned(scenario: Scenario) -> None:
    scenario.tab.status = 403
    scenario.tab.content = (
        '<html><body class="neterror">ERR_HTTP_RESPONSE_CODE_FAILURE</body></html>'
    )
    fetcher = NodriverFetcher(timeout=5, max_bytes=1000)

    response = await fetcher.fetch(Request("GET", "https://example.test/page"))

    assert response.status == 403
    assert response.content == b""
