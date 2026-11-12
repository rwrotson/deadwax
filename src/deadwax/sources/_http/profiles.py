from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version


class Profile(StrEnum):
    """How a client presents itself: honestly to APIs, like a browser to HTML pages."""

    API = "api"
    BROWSER = "browser"


@dataclass(frozen=True, slots=True)
class BrowserIdentity:
    """Headers of one browser, consistent with each other and with escalation transports."""

    name: str
    user_agent: str
    headers: tuple[tuple[str, str], ...]
    impersonate: str | None = None


CHROME = BrowserIdentity(
    name="chrome",
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    ),
    headers=(
        ("sec-ch-ua", '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"'),
        ("sec-ch-ua-mobile", "?0"),
        ("sec-ch-ua-platform", '"macOS"'),
        ("upgrade-insecure-requests", "1"),
        (
            "accept",
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
            "image/apng,*/*;q=0.8",
        ),
        ("sec-fetch-site", "none"),
        ("sec-fetch-mode", "navigate"),
        ("sec-fetch-user", "?1"),
        ("sec-fetch-dest", "document"),
        ("accept-language", "en-US,en;q=0.9"),
    ),
    impersonate="chrome",
)
FIREFOX = BrowserIdentity(
    name="firefox",
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:144.0) Gecko/20100101 Firefox/144.0"
    ),
    headers=(
        ("accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        ("accept-language", "en-US,en;q=0.5"),
        ("upgrade-insecure-requests", "1"),
        ("sec-fetch-dest", "document"),
        ("sec-fetch-mode", "navigate"),
        ("sec-fetch-site", "none"),
        ("sec-fetch-user", "?1"),
    ),
    impersonate="firefox",
)
BROWSERS = (CHROME, FIREFOX)


def package_version() -> str:
    """Return the installed deadwax version, or '0' when running from an unbuilt tree."""
    try:
        return version("deadwax")
    except PackageNotFoundError:
        return "0"


def api_headers(contact: str) -> dict[str, str]:
    """Return headers with the honest User-Agent that API policies require."""
    return {
        "user-agent": f"deadwax/{package_version()} (+{contact})",
        "accept": "application/json",
    }


def browser_headers(identity: BrowserIdentity) -> dict[str, str]:
    """Return the full header set of a browser navigation request."""
    return {"user-agent": identity.user_agent, **dict(identity.headers)}
