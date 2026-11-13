from collections.abc import Mapping

# Interstitials that replace the page whatever the status; matched case-insensitively.
_CHALLENGE_MARKERS = (
    ("<title>just a moment...</title>", "Cloudflare challenge"),
    ("cf-browser-verification", "Cloudflare challenge"),
    ("/cdn-cgi/challenge-platform/", "Cloudflare challenge"),
    ("captcha-delivery.com", "DataDome captcha"),
    ("/_fs-ch-", "Fastly client challenge"),
    ("sucuri_cloudproxy_js", "Sucuri challenge"),
)

# Captcha widgets also appear on ordinary pages, so they count only on a refusal.
_REFUSAL_MARKERS = (
    ("attention required! | cloudflare", "Cloudflare block page"),
    ("px-captcha", "PerimeterX captcha"),
    ("g-recaptcha", "reCAPTCHA"),
    ("h-captcha", "hCaptcha"),
    ("cf-turnstile", "Cloudflare Turnstile"),
    ("errors.edgesuite.net", "Akamai block"),
    ("errors&#46;edgesuite&#46;net", "Akamai block"),
)
_SCAN_BYTES = 32_768
_REFUSAL_STATUSES = frozenset({403, 429, 503})


def detect_challenge(status: int, headers: Mapping[str, str], body: bytes) -> str | None:
    """Name the anti-bot challenge a response shows, or return None for an ordinary page."""
    lowered = {name.lower(): value.lower() for name, value in headers.items()}
    if lowered.get("cf-mitigated") == "challenge":
        return "Cloudflare challenge"
    refused = status in _REFUSAL_STATUSES
    if refused and "x-datadome" in lowered:
        return "DataDome block"
    text = body[:_SCAN_BYTES].decode("utf-8", "replace").lower()
    markers = _CHALLENGE_MARKERS + _REFUSAL_MARKERS if refused else _CHALLENGE_MARKERS
    for marker, name in markers:
        if marker in text:
            return name
    if status in {403, 503} and lowered.get("server") == "cloudflare":
        return f"Cloudflare HTTP {status}"
    return None
