import importlib.metadata

import pytest

from deadwax.sources._http import BROWSERS, CHROME, api_headers, browser_headers, profiles


def test_api_headers_identify_deadwax_honestly() -> None:
    headers = api_headers("https://example.org/contact")

    assert headers["user-agent"] == (
        f"deadwax/{importlib.metadata.version('deadwax')} (+https://example.org/contact)"
    )
    assert headers["accept"] == "application/json"


def test_unbuilt_tree_reports_version_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(profiles, "version", missing)

    assert profiles.package_version() == "0"


@pytest.mark.parametrize("identity", BROWSERS)
def test_browser_headers_match_their_browser(identity: profiles.BrowserIdentity) -> None:
    headers = browser_headers(identity)

    assert headers["user-agent"] == identity.user_agent
    assert identity.name.capitalize() in identity.user_agent
    assert "deadwax" not in identity.user_agent
    assert ("sec-ch-ua" in headers) is (identity is CHROME)
    assert all(name == name.lower() for name in headers)
