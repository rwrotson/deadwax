import contextlib
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit, urlunsplit

from deadwax.core import ConfigurationError, SourceError
from deadwax.sources._http.messages import (
    Request,
    Response,
    ResponseTooLargeError,
    TransportError,
)
from deadwax.sources._http.profiles import CHROME, BrowserIdentity
from deadwax.sources.config import DIRECT

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright
    from playwright.async_api import Response as PageResponse

MISSING_EXTRA = (
    "browser fetching needs the 'browser' extra: pip install 'deadwax[browser]', "
    "then run 'playwright install chromium'"
)
MISSING_BROWSER = "Chromium for Playwright is not installed: run 'playwright install chromium'"

# A challenge page reloads itself once solved; this bounds the wait for that, in milliseconds.
_SETTLE_MS = 5000.0


def launch_proxy(proxy: str | None) -> dict[str, Any]:
    """Chromium launch options for a proxy setting; Chromium ignores proxy variables."""
    if proxy is None:
        return {}
    if proxy == DIRECT:
        return {"args": ["--no-proxy-server"]}
    parts = urlsplit(proxy)
    server = urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))
    options = {"server": server}
    if parts.username is not None:
        options["username"] = unquote(parts.username)
        options["password"] = unquote(parts.password or "")
    return {"proxy": options}


class BrowserFetcher:
    """Headless Chromium that loads pages the way a visitor's browser does."""

    name = "browser"

    def __init__(
        self,
        *,
        timeout: float,
        max_bytes: int,
        identity: BrowserIdentity = CHROME,
        proxy: str | None = None,
    ) -> None:
        try:
            import playwright.async_api  # noqa: F401, PLC0415 -- optional extra (R7)
        except ImportError as error:
            raise ConfigurationError(MISSING_EXTRA) from error
        self._timeout_ms = timeout * 1000
        self._max_bytes = max_bytes
        self._identity = identity
        self._proxy = proxy
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def _open(self) -> BrowserContext:
        from playwright.async_api import Error, async_playwright  # noqa: PLC0415 -- optional (R7)

        if self._context is None:
            self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    **launch_proxy(self._proxy),
                )
            except Error as error:
                await self.aclose()
                raise ConfigurationError(MISSING_BROWSER) from error
            accept_language = dict(self._identity.headers).get("accept-language", "en-US")
            self._context = await self._browser.new_context(
                user_agent=self._identity.user_agent,
                locale="en-US",
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"accept-language": accept_language},
            )
        return self._context

    async def fetch(self, request: Request) -> Response:
        """Load the page, wait for a challenge to clear, and return the rendered HTML."""
        from playwright.async_api import Error  # noqa: PLC0415 -- optional extra (R7)

        if request.method != "GET":
            raise SourceError(f"the browser transport cannot send {request.method} requests")
        context = await self._open()
        page = await context.new_page()
        navigations: list[PageResponse] = []

        def record(response: PageResponse) -> None:
            if response.request.is_navigation_request() and response.frame == page.main_frame:
                navigations.append(response)

        page.on("response", record)
        try:
            await page.goto(
                request.full_url,
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            )

            # Pages that keep polling never become idle; the DOM is loaded by then anyway.
            with contextlib.suppress(Error):
                await page.wait_for_load_state("networkidle", timeout=_SETTLE_MS)

            content = (await page.content()).encode()
            final = navigations[-1] if navigations else None
            headers = await final.all_headers() if final is not None else {}
            url = page.url
        except Error as error:
            raise TransportError(f"{type(error).__name__}: {error}") from error
        finally:
            await page.close()
        if len(content) > self._max_bytes:
            raise ResponseTooLargeError(f"response is larger than {self._max_bytes} bytes")
        status = final.status if final is not None else 200
        return Response(url=url, status=status, content=content, headers=headers)

    async def aclose(self) -> None:
        """Close the browser and stop Playwright."""
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._context = self._browser = self._playwright = None
