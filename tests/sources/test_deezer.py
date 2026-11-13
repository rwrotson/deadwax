import json

import httpx
import pytest

from deadwax.core import (
    EntityKind,
    Identity,
    IdKind,
    LookupContext,
    NotFoundError,
    Provenance,
    Query,
    RateLimitedError,
    Sourced,
    SourceError,
    parse_query,
)
from deadwax.sources import SourcesConfig, SourceSettings
from deadwax.sources._http import HttpResources
from deadwax.sources.deezer import DeezerAdapter, check

# Hand-written responses in the shape Deezer documents; the API refused our network, so none
# could be recorded.
ARTIST = {"id": 399, "name": "Radiohead", "link": "https://www.deezer.com/artist/399"}
TRACK = {
    "id": 138539973,
    "title": "Paranoid Android",
    "isrc": "GBAYE9701376",
    "link": "https://www.deezer.com/track/138539973",
    "preview": "https://cdn-preview.dzcdn.net/stream/x.mp3",
    "release_date": "1997-05-21",
    "artist": ARTIST,
    "album": {
        "id": 14880539,
        "title": "OK Computer",
        "link": "https://www.deezer.com/album/14880539",
    },
}
ALBUM = {
    "id": 14880539,
    "title": "OK Computer",
    "upc": "634904078164",
    "link": "https://www.deezer.com/album/14880539",
    "label": "XL Recordings",
    "release_date": "1997-05-21",
    "artist": ARTIST,
    "genres": {"data": [{"id": 152, "name": "Rock"}]},
}
SOURCES = [Provenance(source="musicbrainz")]


def serve(routes: dict[str, object]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(
            request.url.path,
            {"error": {"type": "DataException", "message": "no data", "code": 800}},
        )
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def adapter(routes: dict[str, object]) -> DeezerAdapter:
    config = SourcesConfig(deezer=SourceSettings(rate=1000))
    return DeezerAdapter(config, HttpResources(transport=serve(routes)))


def context(query: Query, **identity: object) -> LookupContext:
    return LookupContext(query=query, identity=Identity.model_validate(identity))


@pytest.mark.asyncio
async def test_track_by_isrc_from_an_earlier_pass() -> None:
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)
    isrcs = [Sourced(value="GBAYE9701376", sources=SOURCES)]

    partial = await adapter({"/track/isrc:GBAYE9701376": TRACK}).lookup(
        query,
        context(query, isrcs=isrcs),
    )

    assert partial.candidate is not None
    assert partial.candidate.isrcs == ["GBAYE9701376"]
    assert partial.candidate.ids == {IdKind.DEEZER: "138539973"}
    assert [(link.target, link.preview_url is not None) for link in partial.links] == [
        ("track", True),
        ("album", False),
        ("artist", False),
    ]


@pytest.mark.asyncio
async def test_track_search_skips_other_versions() -> None:
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)
    live = TRACK | {"id": 1, "title": "Paranoid Android (Live)"}
    routes = {"/search/track": {"data": [live, TRACK]}, "/track/138539973": TRACK}

    partial = await adapter(routes).lookup(query, context(query))

    assert partial.candidate is not None
    assert partial.candidate.url == TRACK["link"]


@pytest.mark.asyncio
async def test_album_by_barcode_and_by_search() -> None:
    query = parse_query("Radiohead - OK Computer", EntityKind.ALBUM)
    upcs = [Sourced(value="634904078164", sources=SOURCES)]
    routes = {
        "/album/upc:634904078164": ALBUM,
        "/search/album": {"data": [ALBUM]},
        "/album/14880539": ALBUM,
    }

    by_upc = await adapter(routes).lookup(query, context(query, upcs=upcs))
    searched = await adapter(routes).lookup(query, context(query))

    assert by_upc == searched
    assert by_upc.candidate is not None
    assert [label.name for label in by_upc.candidate.labels] == ["XL Recordings"]
    assert by_upc.candidate.upcs == ["634904078164"]
    assert [tag.name for tag in by_upc.tags] == ["Rock"]


@pytest.mark.asyncio
async def test_deezer_urls_are_resolved_by_id() -> None:
    track_query = parse_query("https://www.deezer.com/track/138539973")
    album_query = parse_query("https://www.deezer.com/album/14880539")
    routes: dict[str, object] = {"/track/138539973": TRACK, "/album/14880539": ALBUM}
    deezer = adapter(routes)

    track = await deezer.lookup(track_query, context(track_query))
    album = await deezer.lookup(album_query, context(album_query))

    assert deezer.resolves(track_query)
    assert not deezer.resolves(parse_query("Radiohead - OK Computer", EntityKind.ALBUM))
    assert track.candidate is not None
    assert track.candidate.kind is EntityKind.TRACK
    assert album.candidate is not None
    assert album.candidate.kind is EntityKind.ALBUM


@pytest.mark.parametrize(
    ("query", "routes"),
    [
        (
            parse_query("Radiohead - Paranoid Android", EntityKind.TRACK),
            {"/search/track": {"data": []}},
        ),
        (parse_query("Radiohead - OK Computer", EntityKind.ALBUM), {"/search/album": {"data": []}}),
        (parse_query("https://bandcamp.example/x"), {}),
    ],
)
@pytest.mark.asyncio
async def test_nothing_found(query: Query, routes: dict[str, object]) -> None:
    with pytest.raises(NotFoundError):
        await adapter(routes).lookup(query, context(query))


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        ({"code": 800, "message": "no data"}, NotFoundError),
        ({"code": 4, "message": "Quota limit exceeded"}, RateLimitedError),
        ({"code": 300, "type": "OAuthException", "message": "invalid token"}, SourceError),
    ],
)
def test_errors_inside_successful_responses(
    error: dict[str, object],
    raised: type[Exception],
) -> None:
    with pytest.raises(raised):
        check(json.dumps({"error": error}).encode(), "https://api.deezer.com/x")
    check(b'{"id": 1}', "https://api.deezer.com/x")
