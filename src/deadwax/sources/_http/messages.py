import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode

from deadwax.core import SourceError


class TransportError(SourceError):
    """The request failed before a response arrived."""


class ResponseTooLargeError(SourceError):
    """The response exceeded the configured size limit."""


@dataclass(frozen=True, slots=True)
class Request:
    """HTTP request as transports see it; headers are the caller's, not the profile's."""

    method: str
    url: str
    params: tuple[tuple[str, str], ...] = ()
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes | None = None

    @property
    def full_url(self) -> str:
        """URL with the query string."""
        if not self.params:
            return self.url
        separator = "&" if "?" in self.url else "?"
        return f"{self.url}{separator}{urlencode(self.params)}"


@dataclass(frozen=True, slots=True)
class Response:
    """HTTP response with lowercase header names."""

    url: str
    status: int
    content: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether the status is 2xx."""
        return 200 <= self.status < 300  # noqa: PLR2004 -- the 2xx status range

    @property
    def text(self) -> str:
        """Body decoded with the charset of the Content-Type header, UTF-8 by default."""
        content_type = self.headers.get("content-type", "")
        charset = "utf-8"
        for part in content_type.split(";")[1:]:
            name, _, value = part.strip().partition("=")
            if name.lower() == "charset" and value:
                charset = value.strip("\"'")
        try:
            return self.content.decode(charset, "replace")
        except LookupError:
            return self.content.decode("utf-8", "replace")

    def json(self) -> object:
        """Body parsed as JSON."""
        return json.loads(self.content)


class Fetcher(Protocol):
    """Transport that performs one request without retries, caching, or rate limits."""

    @property
    def name(self) -> str:
        """Transport name used in logs and errors."""
        ...

    async def fetch(self, request: Request) -> Response:
        """Send the request; raise `TransportError` when no response arrives."""
        ...

    async def aclose(self) -> None:
        """Release connections, sessions, or browsers."""
        ...


def lower_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return headers with lowercase names."""
    return {name.lower(): value for name, value in headers.items()}
