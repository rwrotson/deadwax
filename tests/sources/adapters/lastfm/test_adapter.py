import json

import httpx
import pytest

from deadwax.core import (
    Capability,
    EntityKind,
    EntityType,
    LookupContext,
    NotFoundError,
    Provenance,
    Query,
    RecordCandidate,
    RecordIdentity,
    Scope,
    Sourced,
    SourceState,
)
from deadwax.sources import LookupConfig, parse_query
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.lastfm import LastfmAdapter
from deadwax.sources.adapters.lastfm.adapter import API, _artist_page

TRACK_URL = "https://www.last.fm/music/Band/_/Song"
ALBUM_URL = "https://www.last.fm/music/Band/Record"
TAGS = {"toptags": {"tag": [{"name": "dub", "count": 100}, {"name": "rare", "count": 0}]}}
METHODS: dict[str, object] = {
    "track.getInfo": {"track": {"name": "Song", "url": TRACK_URL,
                                "artist": {"name": "Band", "url": "https://www.last.fm/music/Band"},
                                "wiki": {"summary": "About the song."}}},
    "track.getTopTags": TAGS,
    "track.getSimilar": {"similartracks": {"track": [
        {"name": "Next", "match": 0.9, "artist": {"name": "Other"}}]}},
    "album.getInfo": {"album": {"name": "Record", "artist": "Band", "url": ALBUM_URL}},
    "album.getTopTags": TAGS,
    "artist.getTopTags": {"toptags": {"tag": {"name": "bass", "count": 50}}},
    "artist.getSimilar": {"similarartists": {"artist": [{"name": "Kin", "match": "0.7"}]}},
}  # fmt: skip


def make(
    methods: dict[str, object] | None = None,
    *,
    key: str | None = "k3y",
    seen: list[httpx.Request] | None = None,
) -> LastfmAdapter:
    table = METHODS | (methods or {})

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        method = request.url.params["method"]
        return httpx.Response(200, content=json.dumps(table[method]).encode())

    config = LookupConfig.model_validate(
        {
            "sources": {"lastfm": {"rate": 1000, "api_key": key}},
            "http": {"retries": 0, "escalation": []},
        },
    )
    return LastfmAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


TRACK = parse_query("Band - Song", EntityKind.TRACK)
ALBUM = parse_query("Band - Record", EntityKind.ALBUM)


@pytest.mark.asyncio
async def test_track() -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen=seen)

    partial = await adapter.lookup(TRACK, LookupContext(query=TRACK))
    await adapter.aclose()

    assert isinstance(partial.candidate, RecordCandidate)
    assert (partial.candidate.artist, partial.candidate.title) == ("Band", "Song")
    assert [(t.name, t.scope, t.weight) for t in partial.tags] == [
        ("dub", Scope.RECORDING, 1.0),
        ("bass", Scope.ARTIST, 0.5),
    ]
    assert partial.tags[1].sources[0].url == "https://www.last.fm/music/Band"
    assert [t.body for t in partial.texts] == ["About the song."]
    assert [(r.target.type, r.target.name, r.scope) for r in partial.relations] == [
        (EntityType.RECORDING, "Next", Scope.RECORDING),
        (EntityType.ARTIST, "Kin", Scope.ARTIST),
    ]
    assert partial.relations[0].target.artist == "Other"
    assert partial.relations[1].sources[0].url == "https://www.last.fm/music/Band"
    similar_artists = next(r for r in seen if r.url.params["method"] == "artist.getSimilar")
    assert (similar_artists.url.params["artist"], similar_artists.url.params["limit"]) == (
        "Band",
        "10",
    )
    first = seen[0].url.params
    assert (first["method"], first["autocorrect"], first["api_key"]) == (
        "track.getInfo",
        "1",
        "k3y",
    )
    assert str(seen[0].url).startswith(API)


@pytest.mark.asyncio
async def test_album() -> None:
    adapter = make()

    partial = await adapter.lookup(ALBUM, LookupContext(query=ALBUM))

    assert partial.candidate is not None
    assert partial.candidate.kind is EntityKind.ALBUM
    assert [(t.name, t.scope) for t in partial.tags] == [
        ("dub", Scope.RELEASE_GROUP),
        ("bass", Scope.ARTIST),
    ]
    assert partial.texts == []
    [similar] = partial.relations
    assert (similar.target.name, similar.note) == ("Kin", "match 0.70")
    assert similar.sources[0].url == "https://www.last.fm/music/Band"


@pytest.mark.asyncio
async def test_url_query_uses_what_earlier_passes_found() -> None:
    query = parse_query("https://example.com/x", EntityKind.TRACK)
    identity = RecordIdentity(
        artist=Sourced(value="Band", sources=[Provenance(source="musicbrainz")]),
        title=Sourced(value="Song", sources=[Provenance(source="musicbrainz")]),
    )

    partial = await make().lookup(query, LookupContext(query=query, identity=identity))

    assert partial.candidate is not None


@pytest.mark.asyncio
async def test_nothing_to_look_up() -> None:
    query = parse_query("https://example.com/x")

    with pytest.raises(NotFoundError):
        await make().lookup(query, LookupContext(query=query))


@pytest.mark.asyncio
async def test_not_found_in_the_body() -> None:
    adapter = make({"track.getInfo": {"error": 6, "message": "Track not found"}})

    with pytest.raises(NotFoundError, match="Track not found"):
        await adapter.lookup(TRACK, LookupContext(query=TRACK))


def test_status_needs_the_key() -> None:
    status = make(key=None).status()

    assert status.state is SourceState.MISSING_CREDENTIAL
    assert status.detail == "needs sources.lastfm.api_key"
    assert make().status().ready


@pytest.mark.parametrize(
    ("url", "artist"),
    [
        (TRACK_URL, "https://www.last.fm/music/Band"),
        (ALBUM_URL, "https://www.last.fm/music/Band"),
        ("https://example.com/x", None),
        (None, None),
    ],
)
def test_artist_page(url: str | None, artist: str | None) -> None:
    assert _artist_page(url) == artist


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "facet", "methods"),
    [
        (TRACK, Capability.TAGS, {"track.getInfo", "track.getTopTags", "artist.getTopTags"}),
        (
            TRACK,
            Capability.RELATIONS,
            {"track.getInfo", "track.getSimilar", "artist.getSimilar"},
        ),
        (TRACK, Capability.TEXTS, {"track.getInfo"}),
        (ALBUM, Capability.TAGS, {"album.getInfo", "album.getTopTags", "artist.getTopTags"}),
        (ALBUM, Capability.RELATIONS, {"album.getInfo", "artist.getSimilar"}),
    ],
)
async def test_asks_only_for_wanted_facets(
    query: Query,
    facet: Capability,
    methods: set[str],
) -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen=seen)

    partial = await adapter.lookup(query, LookupContext(query=query, facets=frozenset({facet})))
    await adapter.aclose()

    assert partial.candidate is not None
    assert {request.url.params["method"] for request in seen} == methods
