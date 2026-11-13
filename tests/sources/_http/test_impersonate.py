import sys
import types
from dataclasses import dataclass, field

import pytest

from deadwax.core import ConfigurationError
from deadwax.sources import HttpSettings
from deadwax.sources._http import (
    ImpersonateFetcher,
    Request,
    ResponseTooLargeError,
    TransportError,
)
from deadwax.sources._http import client as client_module


class FakeRequestsError(Exception):
    pass


@dataclass
class FakeCurlResponse:
    url: str
    status_code: int
    content: bytes
    headers: dict[str, str | None]


@dataclass
class FakeSession:
    kwargs: dict[str, object]
    calls: list[tuple[str, str, dict[str, object]]] = field(default_factory=list)
    closed: bool = False

    async def request(self, method: str, url: str, **kwargs: object) -> FakeCurlResponse:
        self.calls.append((method, url, kwargs))
        if url.endswith("/fail"):
            raise FakeRequestsError("handshake failed")
        return FakeCurlResponse(
            url,
            200,
            b"<html>page</html>",
            {"Content-Type": "text/html", "X": None},
        )

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def sessions(monkeypatch: pytest.MonkeyPatch) -> list[FakeSession]:
    created: list[FakeSession] = []

    def session(**kwargs: object) -> FakeSession:
        created.append(FakeSession(kwargs))
        return created[-1]

    requests = types.ModuleType("curl_cffi.requests")
    requests.AsyncSession = session  # type: ignore[attr-defined]
    requests.RequestsError = FakeRequestsError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", types.ModuleType("curl_cffi"))
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", requests)
    return created


@pytest.mark.asyncio
async def test_impersonated_request(sessions: list[FakeSession]) -> None:
    fetcher = ImpersonateFetcher(timeout=5, max_bytes=100)
    request = Request("GET", "https://www.discogs.com/release/1", (("a", "1"),), (("x", "y"),))

    response = await fetcher.fetch(request)
    await fetcher.aclose()

    [session] = sessions
    assert session.kwargs == {
        "impersonate": "chrome",
        "timeout": 5,
        "allow_redirects": True,
        "proxy": None,
        "trust_env": True,
    }
    assert session.calls == [
        (
            "GET",
            "https://www.discogs.com/release/1",
            {"params": [("a", "1")], "headers": {"x": "y"}, "content": None},
        ),
    ]
    assert response.text == "<html>page</html>"
    assert response.headers == {"content-type": "text/html", "x": ""}
    assert session.closed


@pytest.mark.asyncio
async def test_failures_and_size_limit(sessions: list[FakeSession]) -> None:
    fetcher = ImpersonateFetcher(timeout=5, max_bytes=3)

    with pytest.raises(TransportError, match="FakeRequestsError: handshake failed"):
        await fetcher.fetch(Request("GET", "https://x/fail"))
    with pytest.raises(ResponseTooLargeError):
        await fetcher.fetch(Request("GET", "https://x/ok"))


def test_client_factory_uses_http_settings(sessions: list[FakeSession]) -> None:
    fetcher = client_module._impersonate(HttpSettings(timeout=9), "http://proxy.example:8080")

    assert fetcher.name == "impersonate"
    assert sessions[0].kwargs["timeout"] == 9
    assert sessions[0].kwargs["proxy"] == "http://proxy.example:8080"
    assert sessions[0].kwargs["trust_env"] is False


def test_direct_ignores_the_environment_proxy(sessions: list[FakeSession]) -> None:
    ImpersonateFetcher(timeout=5, max_bytes=3, proxy="direct")

    assert sessions[0].kwargs["proxy"] is None
    assert sessions[0].kwargs["trust_env"] is False


def test_missing_extra_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "curl_cffi", None)

    with pytest.raises(ConfigurationError, match=r"deadwax\[stealth\]"):
        ImpersonateFetcher(timeout=5, max_bytes=3)
