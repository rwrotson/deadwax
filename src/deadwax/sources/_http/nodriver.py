import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from deadwax.core import ConfigurationError, SourceError
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

    def __init__(
        self,
        *,
        timeout: float,
        max_bytes: int,
        proxy: str | None = None,
        headless: bool = True,
    ) -> None:
        try:
            _module()
        except ImportError as error:
            raise ConfigurationError(MISSING_EXTRA) from error
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._proxy = proxy
        self._headless = headless
        self._browser: _Browser | None = None

    async def _open(self) -> _Browser:
        module = _module()

        if self._browser is None:
            args: list[str] = []
            if self._proxy == DIRECT:
                args.append("--no-proxy-server")
            elif self._proxy is not None:
                parts = urlsplit(self._proxy)
                if parts.username is not None:
                    raise ConfigurationError(
                        "Nodriver does not support an authenticated HTTP proxy",
                    )
                server = urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))
                args.append(f"--proxy-server={server}")
            try:
                start = cast(Callable[..., Awaitable[_Browser]], vars(module)["start"])
                self._browser = await start(headless=self._headless, browser_args=args)
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
            await asyncio.wait_for(tab.sleep(1), timeout=self._timeout)
            content = (await asyncio.wait_for(tab.get_content(), timeout=self._timeout)).encode()
            url = tab.url
            navigation_status = await _navigation_status(tab, responses, self._timeout)
        except (TimeoutError, OSError, RuntimeError) as error:
            raise TransportError(f"{type(error).__name__}: {error}") from error
        finally:
            await tab.close()
        final = next(
            (item for item in reversed(responses) if item.url == url),
            responses[-1] if responses else None,
        )
        if final is None and (url == "about:blank" or not content.strip()):
            raise TransportError("Nodriver did not load a document")
        if len(content) > self._max_bytes:
            raise ResponseTooLargeError(f"response is larger than {self._max_bytes} bytes")

        # Chrome can render a navigation without delivering Network.responseReceived to this tab.
        status = final.status if final is not None else navigation_status
        if not isinstance(status, int) or status < _MIN_HTTP_STATUS:
            status = 200
        return Response(
            url=url,
            status=status,
            content=content,
            headers=lower_headers(final.headers) if final is not None else {},
        )

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
