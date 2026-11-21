from pathlib import Path

import httpx
import pytest

from deadwax import ErrorKind, RelationKind, TrackQuery, UnresolvedQuery
from deadwax.sources import PerSourceSettings, TracklistsSettings
from deadwax.sources.config import Escalation, LookupConfig
from deadwax.sources.lookup import lookup

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "tracklists"


@pytest.mark.asyncio
async def test_search_track_and_verified_set() -> None:
    search = (FIXTURES / "search.html").read_bytes()
    track = (FIXTURES / "tracklists.html").read_bytes()
    dj_set = (FIXTURES / "set.html").read_bytes()
    config = LookupConfig(
        sources=PerSourceSettings(
            tracklists=TracklistsSettings(rate=1000, html_transports=(Escalation.HTTPX,)),
        ),
    )

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert b"search_selection=2" in request.content
            return httpx.Response(200, content=search)
        return httpx.Response(200, content=dj_set if "/tracklist/" in request.url.path else track)

    dossier = await lookup(
        TrackQuery(artist="Daft Punk", title="One More Time"),
        config,
        include=["tracklists"],
        transport=httpx.MockTransport(respond),
    )
    assert not dossier.errors
    mix = next(item for item in dossier.relations if item.kind is RelationKind.MIX)
    assert mix.target.artist == "Eric Hamilton"
    assert mix.target.date == "2026-11-11"
    neighbours = [item for item in dossier.relations if item.kind is RelationKind.CO_PLAYED]
    assert {item.note for item in neighbours} == {"before", "after"}
    assert all(item.sources[0].url for item in dossier.relations)


@pytest.mark.asyncio
async def test_missing_track() -> None:
    config = LookupConfig(
        sources=PerSourceSettings(
            tracklists=TracklistsSettings(html_transports=(Escalation.HTTPX,)),
        ),
    )
    dossier = await lookup(
        TrackQuery(artist="Daft Punk", title="One More Time"),
        config,
        include=["tracklists"],
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"<html></html>"),
        ),
    )
    assert dossier.errors[0].kind is ErrorKind.NOT_FOUND


@pytest.mark.asyncio
async def test_blocked_page() -> None:
    config = LookupConfig(
        sources=PerSourceSettings(
            tracklists=TracklistsSettings(html_transports=(Escalation.HTTPX,)),
        ),
    )
    dossier = await lookup(
        TrackQuery(artist="Daft Punk", title="One More Time"),
        config,
        include=["tracklists"],
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                403,
                headers={"cf-mitigated": "challenge"},
                text="Just a moment... Cloudflare",
            ),
        ),
    )
    assert dossier.errors[0].kind is ErrorKind.BLOCKED


@pytest.mark.asyncio
async def test_another_version_adds_no_set_relations() -> None:
    track = (FIXTURES / "tracklists.html").read_bytes()
    config = LookupConfig(
        sources=PerSourceSettings(
            tracklists=TracklistsSettings(html_transports=(Escalation.HTTPX,)),
        ),
    )
    dossier = await lookup(
        TrackQuery(artist="Daft Punk", title="One More Time (Extended Mix)"),
        config,
        include=["tracklists"],
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=track)),
    )
    assert not dossier.relations
    assert dossier.errors[0].kind is ErrorKind.NOT_FOUND


@pytest.mark.asyncio
async def test_direct_track_url_needs_no_search() -> None:
    track = (FIXTURES / "tracklists.html").read_bytes()
    dj_set = (FIXTURES / "set.html").read_bytes()
    config = LookupConfig(
        sources=PerSourceSettings(
            tracklists=TracklistsSettings(rate=1000, html_transports=(Escalation.HTTPX,)),
        ),
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, content=dj_set if "/tracklist/" in request.url.path else track)

    dossier = await lookup(
        UnresolvedQuery(
            url="https://www.1001tracklists.com/track/j4rvgx/daft-punk-one-more-time/index.html",
        ),
        config,
        include=["tracklists"],
        transport=httpx.MockTransport(respond),
    )
    assert any(item.kind is RelationKind.MIX for item in dossier.relations)
