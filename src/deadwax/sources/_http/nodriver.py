import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from deadwax.core import ConfigurationError, SourceError
from deadwax.sources._http.challenge import detect_challenge
from deadwax.sources._http.messages import (
    Request,
    Response,
    ResponseTooLargeError,
    TransportError,
    lower_headers,
)
from deadwax.sources.config import DIRECT


class _NavigationResponse(Protocol):
    url: str
    status: int
    headers: Mapping[str, str]


class _ResourceType(Protocol):
    value: str


class _ResponseEvent(Protocol):
    type_: _ResourceType
    response: _NavigationResponse


class _Tab(Protocol):
    url: str

    async def get(self, url: str) -> object: ...
    async def send(self, command: object) -> object: ...
    async def evaluate(self, expression: str, *, return_by_value: bool) -> object: ...
    async def sleep(self, seconds: float) -> object: ...
    async def get_content(self) -> str: ...
    async def close(self) -> object: ...
    def add_handler(self, event: object, callback: Callable[[object], None]) -> None: ...


class _Browser(Protocol):
    _process: asyncio.subprocess.Process | None

    async def get(self, url: str, *, new_tab: bool) -> _Tab: ...
    async def aclose(self) -> None: ...
    def stop(self) -> None: ...


def _module() -> object:
    import nodriver  # type: ignore[import-untyped]  # noqa: PLC0415 -- optional package lacks py.typed

    return nodriver


MISSING_EXTRA = (
    "Nodriver needs the 'nodriver' extra: pip install 'deadwax[nodriver]' and install Chrome"
)
MISSING_BROWSER = "Chrome for Nodriver is not installed"
_MIN_HTTP_STATUS = 100
_POLL_SECONDS = 0.25


def _proxy_args(proxy: str | None) -> list[str]:
    if proxy == DIRECT:
        return ["--no-proxy-server"]
    if proxy is None:
        return []
    parts = urlsplit(proxy)
    if parts.username is not None:
        raise ConfigurationError("Nodriver does not support an authenticated HTTP proxy")
    server = urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))
    return [f"--proxy-server={server}"]


def _chrome_error_page(content: bytes) -> bool:
    """Whether Chrome rendered its own network error instead of the requested page."""
    return bool(
        re.search(rb"ERR_[A-Z_]+", content)
        and (b'class="neterror"' in content or b"chromewebdata" in content),
    )


def _page_response(
    url: str,
    content: bytes,
    responses: list[_NavigationResponse],
    navigation_status: object,
    max_bytes: int,
) -> Response:
    final = next(
        (item for item in reversed(responses) if item.url == url),
        responses[-1] if responses else None,
    )
    if final is None and (url == "about:blank" or not content.strip()):
        raise TransportError("Nodriver did not load a document")
    if len(content) > max_bytes:
        raise ResponseTooLargeError(f"response is larger than {max_bytes} bytes")
    status = final.status if final is not None else navigation_status
    if not isinstance(status, int) or status < _MIN_HTTP_STATUS:
        status = 200
    return Response(
        url=url,
        status=status,
        content=content,
        headers=lower_headers(final.headers) if final is not None else {},
    )


async def _navigation_status(
    tab: _Tab,
    responses: list[_NavigationResponse],
    wait_seconds: float,
) -> object:
    if responses:
        return 0
    return await asyncio.wait_for(
        tab.evaluate(
            "performance.getEntriesByType('navigation')[0]?.responseStatus || 0",
            return_by_value=True,
        ),
        timeout=wait_seconds,
    )


class NodriverFetcher:
    """Chrome transport controlled through Nodriver."""

    name = "nodriver"

    def __init__(  # noqa: PLR0913 -- transport launch options are independent settings
        self,
        *,
        timeout: float,
        max_bytes: int,
        proxy: str | None = None,
        headless: bool = True,
        browser_path: Path | None = None,
        sandbox: bool = True,
        challenge_wait: float = 5.0,
        profile_dir: Path | None = None,
    ) -> None:
        try:
            _module()
        except ImportError as error:
            raise ConfigurationError(MISSING_EXTRA) from error
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._proxy = proxy
        self._headless = headless
        self._browser_path = browser_path
        self._sandbox = sandbox
        self._challenge_wait = challenge_wait
        self._profile_dir = profile_dir
        self._browser: _Browser | None = None

    async def _open(self) -> _Browser:
        module = _module()

        if self._browser is None:
            args = _proxy_args(self._proxy)
            try:
                start = cast(Callable[..., Awaitable[_Browser]], vars(module)["start"])
                options: dict[str, object] = {"headless": self._headless, "browser_args": args}
                if self._browser_path is not None:
                    options["browser_executable_path"] = str(self._browser_path)
                if self._profile_dir is not None:
                    options["user_data_dir"] = str(self._profile_dir)
                if not self._sandbox:
                    options["sandbox"] = False
                self._browser = await start(**options)
            except (OSError, RuntimeError) as error:
                raise ConfigurationError(MISSING_BROWSER) from error
        return self._browser

    async def fetch(self, request: Request) -> Response:
        """Load a document and return its rendered HTML and final navigation status."""
        module = _module()

        if request.method != "GET":
            raise SourceError(f"the Nodriver transport cannot send {request.method} requests")
        browser = await self._open()
        tab = await browser.get("about:blank", new_tab=True)
        responses: list[_NavigationResponse] = []

        def record(event: object) -> None:
            received = cast(_ResponseEvent, event)
            if received.type_.value == "Document":
                responses.append(received.response)

        network = vars(vars(module)["cdp"])["network"]
        tab.add_handler(vars(network)["ResponseReceived"], record)
        try:
            await asyncio.wait_for(tab.send(vars(network)["enable"]()), timeout=self._timeout)
            await asyncio.wait_for(tab.get(request.full_url), timeout=self._timeout)
            response = await self._ready_response(tab, request, responses)
        except (TimeoutError, OSError, RuntimeError) as error:
            raise TransportError(f"{type(error).__name__}: {error}") from error
        finally:
            await tab.close()
        return response

    async def _ready_response(
        self,
        tab: _Tab,
        request: Request,
        responses: list[_NavigationResponse],
    ) -> Response:
        deadline = asyncio.get_running_loop().time() + self._challenge_wait
        while True:
            content = (await asyncio.wait_for(tab.get_content(), timeout=self._timeout)).encode()
            if _chrome_error_page(content):
                raise TransportError("Chrome could not load the page")
            navigation_status = await _navigation_status(tab, responses, self._timeout)
            response = _page_response(
                tab.url,
                content,
                responses,
                navigation_status,
                self._max_bytes,
            )
            incomplete = (
                request.required_marker is not None and request.required_marker not in content
            )
            if (
                not incomplete
                and detect_challenge(response.status, response.headers, content) is None
            ):
                return response
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return response
            await asyncio.sleep(min(_POLL_SECONDS, remaining))

    async def aclose(self) -> None:
        """Stop the browser and discard its temporary profile."""
        if self._browser is not None:
            browser = self._browser
            process = browser._process
            await browser.aclose()
            browser.stop()
            if process is not None:
                await process.wait()
            await asyncio.sleep(0)
            self._browser = None
