import pytest

from deadwax.sources._http import detect_challenge


@pytest.mark.parametrize(
    ("status", "headers", "body", "expected"),
    [
        (200, {}, b"<html><title>Discogs</title></html>", None),
        (403, {"cf-mitigated": "challenge"}, b"", "Cloudflare challenge"),
        (403, {"X-DataDome": "protected"}, b"", "DataDome block"),
        (200, {"x-datadome": "protected"}, b"<p>ok</p>", None),
        (503, {}, b"<TITLE>Just a moment...</TITLE>", "Cloudflare challenge"),
        (200, {}, b'<script src="/cdn-cgi/challenge-platform/h/b">', "Cloudflare challenge"),
        (200, {}, b"<form class=g-recaptcha>", None),
        (403, {}, b"<div class=g-recaptcha>", "reCAPTCHA"),
        (403, {}, b"Attention Required! | Cloudflare", "Cloudflare block page"),
        (403, {"Server": "cloudflare"}, b"denied", "Cloudflare HTTP 403"),
        (429, {"server": "cloudflare"}, b"slow down", None),
        (404, {"server": "cloudflare"}, b"missing", None),
    ],
)
def test_detects_challenges(
    status: int, headers: dict[str, str], body: bytes, expected: str | None
) -> None:
    assert detect_challenge(status, headers, body) == expected
