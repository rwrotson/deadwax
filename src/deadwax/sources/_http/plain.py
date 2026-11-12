from collections.abc import Mapping

import httpx

from deadwax.sources._http.messages import (
    Request,
    Response,
    ResponseTooLargeError,
    TransportError,
    lower_headers,
)


class HttpxFetcher:
    """Plain httpx transport with HTTP/2, cookies, and a response size limit."""

    name = "httpx"

    def __init__(
        self,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._max_bytes = max_bytes
        self._client = httpx.AsyncClient(
            headers=dict(headers),
            timeout=timeout,
            follow_redirects=True,
            http2=transport is None,
            transport=transport,
        )

    async def fetch(self, request: Request) -> Response:
        """Send the request, reading at most the size limit."""
        try:
            async with self._client.stream(
                request.method,
                request.url,
                params=request.params,
                headers=request.headers,
                content=request.body,
            ) as response:
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise ResponseTooLargeError(
                            f"response is larger than {self._max_bytes} bytes"
                        )
                    chunks.append(chunk)
                return Response(
                    url=str(response.url),
                    status=response.status_code,
                    content=b"".join(chunks),
                    headers=lower_headers(response.headers),
                )
        except httpx.TransportError as error:
            raise TransportError(f"{type(error).__name__}: {error}") from error

    async def aclose(self) -> None:
        """Close the connection pool."""
        await self._client.aclose()
