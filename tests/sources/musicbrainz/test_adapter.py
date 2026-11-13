from collections.abc import Callable

import httpx
import pytest

from deadwax.core import (
    EntityKind,
    Identity,
    IdKind,
    LookupContext,
    NotFoundError,
    Partial,
    Provenance,
    Query,
    Sourced,
    VersionKind,
    parse_query,
)
from deadwax.sources import SourcesConfig, SourceSettings
from deadwax.sources._http import HttpResources
from deadwax.sources.musicbrainz import MusicBrainzAdapter

MBID = "{}0000000-0000-0000-0000-000000000000"
ARTIST = {"id": MBID.format(1), "name": "Everything but the Girl"}
CREDIT = [{"name": ARTIST["name"], "joinphrase": "", "artist": ARTIST}]
RECORDING = {"id": MBID.format(2), "title": "Missing", "artist-credit": CREDIT}
REMIX = {
    "id": MBID.format(3),
    "title": "Missing",
    "disambiguation": "Todd Terry remix",
    "artist-credit": CREDIT,
}
GROUP = {"id": MBID.format(4), "title": "Amplified Heart", "artist-credit": CREDIT}
SOURCES = [Provenance(source="itunes")]

type Route = Callable[[httpx.Request], object]


def respond(routes: dict[str, object]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/ws/2/")
        body = routes.get(path)
        if callable(body):
            body = body(request)
        if body is None:
            return httpx.Response(404, json={"error": "Not Found"})
        return httpx.Response(200, json=body)

    return handler


async def lookup(
    query: Query,
    routes: dict[str, object],
    identity: Identity | None = None,
) -> Partial:
    resources = HttpResources(transport=httpx.MockTransport(respond(routes)))
    config = SourcesConfig(musicbrainz=SourceSettings(rate=1000))
    adapter = MusicBrainzAdapter(config, resources)
    context = LookupContext(query=query, identity=identity or Identity())
    try:
        return await adapter.lookup(query, context)
    finally:
        await adapter.aclose()


def artist_route() -> dict[str, object]:
    return {f"artist/{ARTIST['id']}": ARTIST | {"relations": []}}


@pytest.mark.asyncio
async def test_recording_url_is_read_directly() -> None:
    query = parse_query(f"https://musicbrainz.org/recording/{RECORDING['id']}")
    routes = {f"recording/{RECORDING['id']}": RECORDING, **artist_route()}

    partial = await lookup(query, routes)

    assert partial.candidate is not None
    assert partial.candidate.ids[IdKind.MUSICBRAINZ_RECORDING] == RECORDING["id"]
    assert partial.candidate.labels == []


@pytest.mark.asyncio
async def test_release_url_leads_to_its_release_group() -> None:
    release_id = MBID.format(5)
    query = parse_query(f"https://musicbrainz.org/release/{release_id}")
    routes = {
        f"release/{release_id}": {"id": release_id, "title": "x", "release-group": GROUP},
        f"release-group/{GROUP['id']}": GROUP,
        **artist_route(),
    }

    partial = await lookup(query, routes)

    assert partial.candidate is not None
    assert partial.candidate.kind is EntityKind.ALBUM
    assert partial.candidate.upcs == []


@pytest.mark.asyncio
async def test_release_without_group_is_not_found() -> None:
    release_id = MBID.format(5)
    query = parse_query(f"https://musicbrainz.org/release/{release_id}")

    with pytest.raises(NotFoundError):
        await lookup(query, {f"release/{release_id}": {"id": release_id, "title": "x"}})


@pytest.mark.parametrize(
    "relation",
    [
        {"type": "free streaming", "target-type": "release_group", "release_group": GROUP},
        {
            "type": "download for free",
            "target-type": "release",
            "release": {"id": MBID.format(5), "title": "x"},
        },
    ],
)
@pytest.mark.asyncio
async def test_other_urls_are_looked_up(relation: dict[str, object]) -> None:
    query = parse_query("https://brianleeds.bandcamp.com/album/x")
    routes = {
        "url": {"id": MBID.format(6), "resource": query.url, "relations": [relation]},
        f"release/{MBID.format(5)}": {"id": MBID.format(5), "title": "x", "release-group": GROUP},
        f"release-group/{GROUP['id']}": GROUP,
        **artist_route(),
    }

    partial = await lookup(query, routes)

    assert partial.candidate is not None
    assert partial.candidate.ids[IdKind.MUSICBRAINZ_RELEASE_GROUP] == GROUP["id"]


@pytest.mark.asyncio
async def test_unknown_url_without_earlier_results_is_not_found() -> None:
    query = parse_query("https://brianleeds.bandcamp.com/album/x")
    routes: dict[str, object] = {
        "url": {"id": MBID.format(6), "resource": query.url, "relations": []},
    }

    with pytest.raises(NotFoundError):
        await lookup(query, routes)
    with pytest.raises(NotFoundError):
        await lookup(query, {})


@pytest.mark.asyncio
async def test_isrc_from_an_earlier_pass_finds_the_recording() -> None:
    query = parse_query("https://music.apple.com/us/song/missing/1")
    identity = Identity(
        kind=EntityKind.TRACK,
        artist=Sourced(value="Everything but the Girl", sources=SOURCES),
        title=Sourced(value="Missing", sources=SOURCES),
        isrcs=[
            Sourced(value="GBAAA0000001", sources=SOURCES),
            Sourced(value="GBAAA0000002", sources=SOURCES),
        ],
    )
    routes = {
        "isrc/GBAAA0000002": {"isrc": "GBAAA0000002", "recordings": [REMIX, RECORDING]},
        f"recording/{RECORDING['id']}": RECORDING,
        **artist_route(),
    }

    partial = await lookup(query, routes, identity)

    assert partial.candidate is not None
    assert partial.candidate.ids[IdKind.MUSICBRAINZ_RECORDING] == RECORDING["id"]


@pytest.mark.asyncio
async def test_version_only_in_the_comment_is_found_with_the_base_title() -> None:
    query = parse_query("Everything but the Girl - Missing (Todd Terry Remix)", EntityKind.TRACK)

    def search(request: httpx.Request) -> object:
        by_base_title = 'recording:"Missing" AND' in request.url.params["query"]
        return {"recordings": [RECORDING, REMIX] if by_base_title else []}

    routes = {"recording": search, f"recording/{REMIX['id']}": REMIX, **artist_route()}

    partial = await lookup(query, routes)

    assert partial.candidate is not None
    assert partial.candidate.version is not None
    assert partial.candidate.version.kind is VersionKind.REMIX


@pytest.mark.parametrize(
    "query",
    [
        parse_query("Everything but the Girl - Missing", EntityKind.TRACK),
        parse_query("Everything but the Girl - Walking Wounded", EntityKind.ALBUM),
    ],
)
@pytest.mark.asyncio
async def test_no_match_is_not_found(query: Query) -> None:
    routes: dict[str, object] = {
        "recording": {"recordings": []},
        "release-group": {"release-groups": [GROUP]},
    }

    with pytest.raises(NotFoundError, match="no matching record"):
        await lookup(query, routes)


@pytest.mark.asyncio
async def test_recording_without_artist_credit() -> None:
    query = parse_query(f"https://musicbrainz.org/recording/{RECORDING['id']}")
    anonymous = RECORDING | {"artist-credit": []}

    partial = await lookup(query, {f"recording/{RECORDING['id']}": anonymous})

    assert partial.relations == []
    assert partial.candidate is not None
    assert IdKind.MUSICBRAINZ_ARTIST not in partial.candidate.ids


def test_resolves_musicbrainz_and_spotify_urls() -> None:
    adapter = MusicBrainzAdapter(SourcesConfig(), HttpResources())

    assert adapter.resolves(parse_query("https://open.spotify.com/track/1"))
    assert adapter.resolves(parse_query(f"https://musicbrainz.org/recording/{RECORDING['id']}"))
    assert not adapter.resolves(parse_query("https://music.apple.com/us/song/x/1"))
