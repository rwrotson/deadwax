from pathlib import Path

import pytest

from deadwax import Dossier
from deadwax.cli import settings


@pytest.fixture(autouse=True)
def isolated_user_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the default config file and cache into the test directory."""
    config = tmp_path / "user-config" / "config.toml"
    monkeypatch.setattr(settings, "default_config_file", lambda: config)
    monkeypatch.setattr(settings, "default_cache_file", lambda: tmp_path / "cache.sqlite")
    return config


def _provenance(source: str, url: str | None = None) -> list[dict[str, object]]:
    return [{"source": source, "url": url}]


@pytest.fixture
def dossier() -> Dossier:
    """A dossier with every kind of fact, a discrepancy and an error."""
    mb = _provenance("musicbrainz", "https://musicbrainz.org/recording/r1")
    itunes = _provenance("itunes", "https://music.apple.com/us/song/1")
    return Dossier.model_validate(
        {
            "query": {"kind": "track", "artist": "Everything but the Girl", "title": "Missing"},
            "generated_at": "2026-11-12T00:00:00Z",
            "identity": {
                "kind": "track",
                "artist": {"value": "Everything but the Girl", "sources": mb + itunes},
                "title": {"value": "Missing", "sources": mb},
                "version": {"kind": "remix", "detail": "Todd Terry remix"},
                "date": {"value": "1995", "sources": mb},
                "labels": [
                    {"name": "Blanco y Negro", "catalog_number": "NEG84CD", "sources": mb},
                    {"name": "Atlantic", "sources": mb},
                ],
                "isrcs": [{"value": "GBAHT9500001", "sources": mb}],
                "upcs": [{"value": "0075678723421", "sources": mb}],
                "external_ids": [{"kind": "wikidata", "value": "Q3859219", "sources": mb}],
                "discrepancies": [
                    {
                        "field": "date",
                        "values": [
                            {"value": "1995", "sources": mb},
                            {"value": "1994", "sources": itunes},
                        ],
                    },
                ],
            },
            "tags": [
                {
                    "name": "house",
                    "kind": "genre",
                    "weight": 1.0,
                    "scope": "recording",
                    "sources": mb,
                },
                {"name": "90s", "kind": "tag", "scope": "release", "sources": itunes},
            ],
            "credits": [
                {"role": "remixer", "name": "Todd Terry", "scope": "recording", "sources": mb},
                {
                    "role": "vocal",
                    "name": "Tracey Thorn",
                    "detail": "lead vocals",
                    "scope": "recording",
                    "sources": mb,
                },
            ],
            "texts": [
                {
                    "kind": "review",
                    "body": "x" * 700,
                    "title": "Missing",
                    "publication": "Example Weekly",
                    "author": "A. Critic",
                    "date": "1995-10-01",
                    "rating": {"value": 4, "scale": 5},
                    "scope": "recording",
                    "sources": mb,
                },
                {
                    "kind": "wiki",
                    "body": "A short note.",
                    "rating": {"text": "B+"},
                    "scope": "work",
                    "sources": mb,
                },
                {"kind": "user", "body": "Plain.", "scope": "release", "sources": mb},
            ],
            "relations": [
                {
                    "kind": "remix_of",
                    "target": {
                        "type": "work",
                        "name": "Missing",
                        "url": "https://musicbrainz.org/work/w1",
                    },
                    "note": "the song this recording performs",
                    "scope": "work",
                    "sources": mb,
                },
                {
                    "kind": "member",
                    "target": {"type": "artist", "name": "Ben Watt"},
                    "scope": "artist",
                    "sources": mb,
                },
                {
                    "kind": "compilation",
                    "target": {
                        "type": "release",
                        "name": "Now 32",
                        "artist": "Various",
                        "date": "1995",
                    },
                    "scope": "recording",
                    "sources": mb,
                },
            ],
            "links": [
                {
                    "service": "spotify",
                    "url": "https://open.spotify.com/track/1",
                    "target": "track",
                    "sources": mb,
                },
            ],
            "errors": [
                {"source": "deezer", "kind": "blocked", "reason": "Akamai block (tried httpx)"},
            ],
        },
    )
