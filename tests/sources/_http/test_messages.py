import httpx
import pytest

from deadwax.sources._http import (
    HttpxFetcher,
    Request,
    Response,
    ResponseTooLargeError,
    TransportError,
)


@pytest.mark.parametrize(
    ("url", "params", "expected"),
    [
        ("https://x/a", (), "https://x/a"),
        ("https://x/a", (("q", "a b"),), "https://x/a?q=a+b"),
        ("https://x/a?fmt=json", (("q", "1"),), "https://x/a?fmt=json&q=1"),
    ],
)
def test_full_url(url: str, params: tuple[tuple[str, str], ...], expected: str) -> None:
    assert Request("GET", url, params).full_url == expected


@pytest.mark.parametrize(
    ("content_type", "content", "expected"),
    [
        (None, "Кино".encode(), "Кино"),
        ("text/html; charset=windows-1251", "Кино".encode("cp1251"), "Кино"),
        ('text/html; charset="utf-8"', b"ok", "ok"),
        ("text/html; charset=nonsense", b"ok", "ok"),
        ("text/html; boundary=x", b"ok", "ok"),
    ],
)
def test_text_uses_the_declared_charset(
    content_type: str | None, content: bytes, expected: str
) -> None:
    headers = {"content-type": content_type} if content_type else {}

    response = Response(url="u", status=200, content=content, headers=headers)

    assert response.text == expected


def test_json_and_status() -> None:
    response = Response(url="u", status=204, content=b'{"a": [1]}')

    assert response.json() == {"a": [1]}
    assert response.ok
    assert not Response(url="u", status=302, content=b"").ok


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/fail":
        raise httpx.ConnectError("refused", request=request)
    return httpx.Response(
        200,
        content=request.url.query + b"|" + request.headers["x-extra"].encode(),
        headers={"X-Thing": "1"},
    )


@pytest.mark.asyncio
async def test_httpx_fetcher_sends_profile_and_request_headers() -> None:
    fetcher = HttpxFetcher(
        headers={"user-agent": "deadwax/test"},
        timeout=1,
        max_bytes=100,
        transport=httpx.MockTransport(handler),
    )
    request = Request("GET", "https://x/ok", (("a", "1"),), (("x-extra", "yes"),))

    response = await fetcher.fetch(request)
    await fetcher.aclose()

    assert response.content == b"a=1|yes"
    assert response.headers["x-thing"] == "1"
    assert response.url == "https://x/ok?a=1"


@pytest.mark.asyncio
async def test_httpx_fetcher_limits_size_and_wraps_transport_errors() -> None:
    fetcher = HttpxFetcher(
        headers={}, timeout=1, max_bytes=3, transport=httpx.MockTransport(handler)
    )
    big = Request("GET", "https://x/ok", (("a", "1"),), (("x-extra", "yes"),))

    with pytest.raises(ResponseTooLargeError, match="larger than 3 bytes"):
        await fetcher.fetch(big)
    with pytest.raises(TransportError, match="ConnectError: refused"):
        await fetcher.fetch(Request("GET", "https://x/fail"))
    await fetcher.aclose()
