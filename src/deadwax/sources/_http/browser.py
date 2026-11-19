import asyncio
import contextlib
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit, urlunsplit

from deadwax.core import ConfigurationError, SourceError, pause_adapter_timeout
from deadwax.sources._http.challenge import SOLVE_PROMPT, detect_challenge
from deadwax.sources._http.messages import (
    Request,
    Response,
    ResponseTooLargeError,
    TransportError,
)
from deadwax.sources._http.profiles import CHROME, BrowserIdentity
from deadwax.sources.config import DIRECT

if TYPE_CHECKING:
    from patchright.async_api import Browser, BrowserContext, Page, Playwright
    from patchright.async_api import Response as PageResponse

MISSING_EXTRA = (
    "browser fetching needs the 'browser' extra: pip install 'deadwax[browser]', "
    "then run 'patchright install chromium'"
)
MISSING_BROWSER = "Chromium for Patchright is not installed: run 'patchright install chromium'"

_POLL_SECONDS = 0.25

# Launch errors that mean the browser executable is absent, not that this launch failed.
_MISSING_EXECUTABLE = ("Executable doesn't exist", "is not found at")

logger = logging.getLogger(__name__)


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


def _status(navigations: list[PageResponse]) -> int:
    return navigations[-1].status if navigations else 200


class BrowserFetcher:
    """Patchright Chromium that loads pages the way a visitor's browser does."""

    name = "browser"

    def __init__(  # noqa: PLR0913 -- independent browser launch and request settings
        self,
        *,
        timeout: float,
        max_bytes: int,
        identity: BrowserIdentity = CHROME,
        proxy: str | None = None,
        headless: bool = True,
        channel: str = "chromium",
        challenge_wait: float = 5.0,
        manual_challenge_wait: float = 60.0,
        profile_dir: Path | None = None,
    ) -> None:
        try:
            import patchright.async_api  # noqa: F401, PLC0415 -- optional extra (R7)
        except ImportError as error:
            raise ConfigurationError(MISSING_EXTRA) from error
        self._timeout_ms = timeout * 1000
        self._max_bytes = max_bytes
        self._identity = identity
        self._proxy = proxy
        self._headless = headless
        self._channel = channel
        self._challenge_wait = challenge_wait
        self._manual_challenge_wait = manual_challenge_wait
        self._profile_dir = profile_dir
        self._profile: tempfile.TemporaryDirectory[str] | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._opening = asyncio.Lock()

        # One challenged page at a time is brought to the front of a visible browser.
        self._front = asyncio.Lock()

    async def _open(self) -> BrowserContext:
        async with self._opening:
            return await self._launch()

    async def _launch(self) -> BrowserContext:
        from patchright.async_api import Error, async_playwright  # noqa: PLC0415 -- optional (R7)

        if self._context is None:
            self._playwright = await async_playwright().start()
            try:
                if self._channel == "chrome" or self._profile_dir is not None:
                    if self._profile_dir is None:
                        temporary_profile = tempfile.TemporaryDirectory(
                            prefix="deadwax-patchright-",
                        )
                        self._profile = temporary_profile
                        profile_path = temporary_profile.name
                    else:
                        profile_path = str(self._profile_dir)
                    self._context = await self._playwright.chromium.launch_persistent_context(
                        user_data_dir=profile_path,
                        channel=self._channel,
                        headless=self._headless,
                        no_viewport=True,
                        **launch_proxy(self._proxy),
                    )
                    return self._context
                self._browser = await self._playwright.chromium.launch(
                    headless=self._headless,
                    **launch_proxy(self._proxy),
                )
            except Error as error:
                await self.aclose()
                if any(marker in str(error) for marker in _MISSING_EXECUTABLE):
                    raise ConfigurationError(MISSING_BROWSER) from error
                raise TransportError(f"browser launch failed: {error}") from error
            accept_language = dict(self._identity.headers).get("accept-language", "en-US")
            self._context = await self._browser.new_context(
                user_agent=self._identity.user_agent,
                locale="en-US",
                viewport={"width": 1440, "height": 900},
                extra_http_headers={"accept-language": accept_language},
            )
        return self._context

    async def fetch(self, request: Request) -> Response:
        """Fetch a rendered page or a same-origin browser POST."""
        if request.method == "POST":
            return await self._post(request)
        if request.method != "GET":
            raise SourceError(f"the browser transport cannot send {request.method} requests")
        return await self._get(request)

    async def _post(self, request: Request) -> Response:
        from patchright.async_api import Error  # noqa: PLC0415 -- optional extra (R7)

        context = await self._open()
        page = await context.new_page()
        try:
            return await self._post_from_page(page, request)
        except Error as error:
            raise TransportError(f"{type(error).__name__}: {error}") from error
        finally:
            await page.close()

    async def _get(self, request: Request) -> Response:
        """Load the page, wait for a challenge to clear, and return rendered HTML."""
        from patchright.async_api import Error  # noqa: PLC0415 -- optional extra (R7)

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

            content = await self._ready_content(page, request, navigations)
            final = navigations[-1] if navigations else None
            headers = await final.all_headers() if final is not None else {}
            url = page.url
        except Error as error:
            raise TransportError(f"{type(error).__name__}: {error}") from error
        finally:
            await page.close()
        if len(content) > self._max_bytes:
            raise ResponseTooLargeError(f"response is larger than {self._max_bytes} bytes")
        if final is None:
            raise TransportError("the browser did not receive a document response")
        status = final.status
        return Response(url=url, status=status, content=content, headers=headers)

    async def _post_from_page(self, page: Page, request: Request) -> Response:
        """Send a same-origin POST with the profile's browser cookies."""
        parts = urlsplit(request.full_url)
        origin = urlunsplit((parts.scheme, parts.netloc, "/", "", ""))
        await page.goto(origin, wait_until="domcontentloaded", timeout=self._timeout_ms)
        await self._ready_content(page, Request("GET", origin), [])
        result = await page.evaluate(
            """async ({url, headers, body}) => {
                const response = await fetch(url, {method: 'POST', headers, body});
                return {url: response.url, status: response.status,
                    headers: Object.fromEntries(response.headers.entries()),
                    content: await response.text()};
            }""",
            {
                "url": request.full_url,
                "headers": dict(request.headers),
                "body": request.body.decode("utf-8") if request.body is not None else None,
            },
        )
        content = result["content"].encode()
        if len(content) > self._max_bytes:
            raise ResponseTooLargeError(f"response is larger than {self._max_bytes} bytes")
        return Response(
            url=result["url"],
            status=result["status"],
            content=content,
            headers=result["headers"],
        )

    async def _ready_content(
        self,
        page: Page,
        request: Request,
        navigations: list[PageResponse],
    ) -> bytes:
        """Wait for the page to clear; a visible browser then asks the visitor for help."""
        content, ready = await self._poll(page, request, navigations, self._challenge_wait)
        if ready or self._headless or detect_challenge(_status(navigations), {}, content) is None:
            return content
        async with pause_adapter_timeout(), self._front:
            await page.bring_to_front()
            logger.warning(SOLVE_PROMPT, page.url, self._manual_challenge_wait)
            content, _ = await self._poll(
                page,
                request,
                navigations,
                self._manual_challenge_wait,
            )
        return content

    async def _poll(
        self,
        page: Page,
        request: Request,
        navigations: list[PageResponse],
        wait: float,
    ) -> tuple[bytes, bool]:
        """Return the content once it is ready or the wait ends, and whether it is ready."""
        from patchright.async_api import Error  # noqa: PLC0415 -- optional extra (R7)

        deadline = asyncio.get_running_loop().time() + wait
        while True:
            try:
                content = (await page.content()).encode()
            except Error as error:
                if (
                    "page is navigating and changing the content" not in str(error)
                    or asyncio.get_running_loop().time() >= deadline
                ):
                    raise
                await asyncio.sleep(_POLL_SECONDS)
                continue
            incomplete = (
                request.required_marker is not None and request.required_marker not in content
            )
            if not incomplete and detect_challenge(_status(navigations), {}, content) is None:
                return content, True
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return content, False
            await asyncio.sleep(min(_POLL_SECONDS, remaining))

    async def aclose(self) -> None:
        """Close the browser and stop Patchright."""
        from patchright.async_api import Error  # noqa: PLC0415 -- optional extra (R7)

        try:
            if self._context is not None:
                with contextlib.suppress(Error):
                    await self._context.close()
            if self._browser is not None:
                with contextlib.suppress(Error):
                    await self._browser.close()
        finally:
            if self._playwright is not None:
                with contextlib.suppress(Error):
                    await self._playwright.stop()
            if self._profile is not None:
                self._profile.cleanup()
                self._profile = None
            self._context = self._browser = self._playwright = None
