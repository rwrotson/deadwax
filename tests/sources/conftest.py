import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import pytest

from deadwax.sources import SourcesConfig

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SECRET_PARAMS = frozenset({"key", "api_key", "token"})

# Fast limits so replayed lookups do not wait between requests.
FAST = {"rate": 1000}


def fixture_key(request: httpx.Request) -> str:
    """Key of a request in the fixtures: method and URL with sorted, non-secret parameters."""
    parts = urlsplit(str(request.url))
    params = sorted((k, v) for k, v in parse_qsl(parts.query) if k not in SECRET_PARAMS)
    return f"{request.method} {urlunsplit(parts._replace(query=urlencode(params)))}"


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
        return httpx.Response(
            int(str(recorded["status"])),
            headers={"content-type": str(recorded["content_type"])},
            content=str(recorded["body"]).encode(),
        )

    return httpx.MockTransport(handler)


def fast_config(**changes: object) -> SourcesConfig:
    """Configuration without rate-limit waits and without a cache."""
    fields: dict[str, object] = {
        name: dict(FAST) for name in ("musicbrainz", "itunes", "deezer", "odesli")
    }
    return SourcesConfig.model_validate(fields | changes)


@pytest.fixture
def replay() -> Callable[..., httpx.MockTransport]:
    return transport


@pytest.fixture
def config() -> SourcesConfig:
    return fast_config()
