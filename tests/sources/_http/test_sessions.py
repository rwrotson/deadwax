import asyncio
from dataclasses import dataclass, field

import pytest

from deadwax.core import ConfigurationError
from deadwax.sources import Escalation, HttpSettings
from deadwax.sources._http import BrowserSessions, Fetcher, Request, Response

URL = "https://example.org/"
SETTINGS = HttpSettings()


@dataclass
class Browser:
    headless: bool
    name: str = "browser"
    closed: bool = False

    async def fetch(self, request: Request) -> Response:
        return Response(url=request.url, status=200, content=b"ok")

    async def aclose(self) -> None:
        self.closed = True


@dataclass
class Factory:
    opened: list[Browser] = field(default_factory=list)
    proxies: list[str | None] = field(default_factory=list)
    error: ConfigurationError | None = None

    def __call__(self, settings: HttpSettings, proxy: str | None) -> Fetcher:
        if self.error is not None:
            raise self.error
        browser = Browser(headless=settings.browser_headless)
        self.opened.append(browser)
        self.proxies.append(proxy)
        return browser


async def borrow(
    sessions: BrowserSessions,
    factory: Factory,
    *,
    headed: bool = False,
    proxy: str | None = None,
    hold: float = 0,
) -> Browser:
    async with sessions.use(
        Escalation.BROWSER,
        factory,
        SETTINGS,
        proxy,
        headed=headed,
    ) as fetcher:
        await asyncio.sleep(hold)
        assert isinstance(fetcher, Browser)
        return fetcher


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_browser() -> None:
    sessions = BrowserSessions()
    factory = Factory()

    lent = await asyncio.gather(*(borrow(sessions, factory, hold=0.01) for _ in range(5)))

    [browser] = factory.opened
    assert all(fetcher is browser for fetcher in lent)
    assert browser.headless
    assert not browser.closed


@pytest.mark.asyncio
async def test_a_headed_request_upgrades_after_open_pages_finish() -> None:
    sessions = BrowserSessions()
    factory = Factory()
    headless = asyncio.create_task(borrow(sessions, factory, hold=0.02))
    await asyncio.sleep(0)

    headed = await borrow(sessions, factory, headed=True)
    first = await headless

    assert first.headless
    assert first.closed
    assert not headed.headless
    assert factory.opened == [first, headed]


@pytest.mark.asyncio
async def test_a_headed_browser_serves_headless_requests() -> None:
    sessions = BrowserSessions()
    factory = Factory()

    headed = await borrow(sessions, factory, headed=True)
    later = await borrow(sessions, factory)

    assert later is headed
    assert len(factory.opened) == 1


@pytest.mark.asyncio
async def test_each_proxy_gets_its_own_browser() -> None:
    sessions = BrowserSessions()
    factory = Factory()

    await borrow(sessions, factory)
    await borrow(sessions, factory, proxy="direct")
    await borrow(sessions, factory, proxy="direct")

    assert factory.proxies == [None, "direct"]


@pytest.mark.asyncio
async def test_a_failing_launch_does_not_hold_the_session() -> None:
    sessions = BrowserSessions()
    factory = Factory(error=ConfigurationError("missing"))

    with pytest.raises(ConfigurationError, match="missing"):
        await borrow(sessions, factory)
    factory.error = None
    browser = await borrow(sessions, factory)

    assert factory.opened == [browser]


@pytest.mark.asyncio
async def test_a_browser_that_cannot_run_is_closed_and_replaced() -> None:
    sessions = BrowserSessions()
    factory = Factory()

    with pytest.raises(ConfigurationError):
        async with sessions.use(Escalation.BROWSER, factory, SETTINGS, None, headed=False):
            raise ConfigurationError("not installed")
    replacement = await borrow(sessions, factory)

    first, second = factory.opened
    assert first.closed
    assert second is replacement


@pytest.mark.asyncio
async def test_aclose_closes_every_browser() -> None:
    sessions = BrowserSessions()
    factory = Factory()
    await borrow(sessions, factory)
    await borrow(sessions, factory, proxy="direct")

    await sessions.aclose()

    assert all(browser.closed for browser in factory.opened)
