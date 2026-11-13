from typing import TYPE_CHECKING

from deadwax.core import ConfigurationError
from deadwax.sources._http.messages import (
    Request,
    Response,
    ResponseTooLargeError,
    TransportError,
    lower_headers,
)
from deadwax.sources._http.profiles import CHROME, BrowserIdentity

if TYPE_CHECKING:
    from curl_cffi.requests import AsyncSession
    from curl_cffi.requests import Response as CurlResponse

MISSING_EXTRA = "TLS impersonation needs the 'stealth' extra: pip install 'deadwax[stealth]'"


class ImpersonateFetcher:
    """curl_cffi transport whose TLS and HTTP/2 fingerprint matches a real browser."""

    name = "impersonate"

    def __init__(
        self,
        *,
        timeout: float,
        max_bytes: int,
        identity: BrowserIdentity = CHROME,
    ) -> None:
        try:
            from curl_cffi.requests import AsyncSession  # noqa: PLC0415 -- optional extra (R7)
        except ImportError as error:
            raise ConfigurationError(MISSING_EXTRA) from error
        self._max_bytes = max_bytes
        self._session: AsyncSession[CurlResponse] = AsyncSession(
            impersonate=identity.impersonate,
            timeout=timeout,
            allow_redirects=True,
        )

    async def fetch(self, request: Request) -> Response:
        """Send the request with the browser's own headers plus the caller's."""
        from curl_cffi.requests import RequestsError  # noqa: PLC0415 -- optional extra (R7)

        try:
            response = await self._session.request(
                request.method,  # type: ignore[arg-type]  # HttpMethod is a Literal of verbs
                request.url,
                params=list(request.params),
                headers=dict(request.headers),
                content=request.body,
            )
        except RequestsError as error:
            raise TransportError(f"{type(error).__name__}: {error}") from error
        if len(response.content) > self._max_bytes:
            raise ResponseTooLargeError(f"response is larger than {self._max_bytes} bytes")
        return Response(
            url=str(response.url),
            status=response.status_code,
            content=response.content,
            headers=lower_headers({k: v or "" for k, v in response.headers.items()}),
        )

    async def aclose(self) -> None:
        """Close the session."""
        await self._session.close()
