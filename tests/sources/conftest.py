import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import pytest

from deadwax.sources import SourcesConfig

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SECRET_PARAMS = frozenset({"key", "api_key", "token", "client_id"})

# Fast limits so replayed lookups do not wait between requests.
FAST = {"rate": 1000}
SOURCES = (
    "musicbrainz", "itunes", "deezer", "odesli", "discogs", "bandcamp", "lastfm", "wikipedia",
    "listenbrainz", "secondhandsongs", "kexp", "spotify", "youtube", "soundcloud",
)  # fmt: skip


def fixture_key(request: httpx.Request) -> str:
    """Fixture key: method, URL with sorted non-secret parameters, and a body hash."""
    parts = urlsplit(str(request.url))
    params = sorted((k, v) for k, v in parse_qsl(parts.query) if k not in SECRET_PARAMS)
    key = f"{request.method} {urlunsplit(parts._replace(query=urlencode(params)))}"
    if request.content:
        key += f" #{hashlib.sha256(request.content).hexdigest()[:16]}"
    return key


def load(scenario: str) -> dict[str, dict[str, object]]:
    """Load the recorded interactions of every source for a scenario."""
    interactions: dict[str, dict[str, object]] = {}
    for path in sorted(FIXTURES.glob(f"*/{scenario}.json")):
        interactions.update(json.loads(path.read_text())["interactions"])
    if not interactions:
        raise FileNotFoundError(f"no fixtures for {scenario}")
    return interactions


def transport(scenario: str, seen: list[str] | None = None) -> httpx.MockTransport:
    """Serve the recorded responses of a scenario; an unrecorded request fails the test."""
    interactions = load(scenario)

    def handler(request: httpx.Request) -> httpx.Response:
        key = fixture_key(request)
        if seen is not None:
            seen.append(key)
        recorded = interactions.get(key)
        if recorded is None:
            raise AssertionError(f"no recorded response for {key}")
        headers = {"content-type": str(recorded["content_type"])}
        if "location" in recorded:
            headers["location"] = str(recorded["location"])
        return httpx.Response(
            int(str(recorded["status"])),
            headers=headers,
            content=str(recorded["body"]).encode(),
        )

    return httpx.MockTransport(handler)


def fast_config(**changes: object) -> SourcesConfig:
    """Configuration without rate-limit waits, cache, or escalation.

    Escalation stays off because curl_cffi opens its own sockets, which pytest-socket
    cannot block, and Playwright would launch a browser.
    """
    fields: dict[str, object] = {name: dict(FAST) for name in SOURCES}
    fields["lastfm"] = {**FAST, "api_key": "test-key"}
    fields["spotify"] = {**FAST, "client_id": "test-id", "client_secret": "test-secret"}
    fields["youtube"] = {**FAST, "api_key": "test-key"}
    fields["soundcloud"] = {**FAST, "client_id": "test-id"}
    fields["http"] = {"escalation": "none"}
    return SourcesConfig.model_validate(fields | changes)


@pytest.fixture
def replay() -> Callable[..., httpx.MockTransport]:
    return transport


@pytest.fixture
def config() -> SourcesConfig:
    return fast_config()


@pytest.fixture
def recorded() -> Callable[[str, str], bytes]:
    """Return the recorded body of one request of a scenario."""

    def body(scenario: str, key: str) -> bytes:
        return str(load(scenario)[key]["body"]).encode()

    return body
