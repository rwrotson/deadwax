import json

import httpx
import pytest

from deadwax.core import (
    EntityKind,
    EntityType,
    ExternalId,
    Identity,
    IdKind,
    LookupContext,
    NotFoundError,
    Provenance,
    RelationKind,
    Scope,
    TextKind,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.kexp import KexpAdapter
from deadwax.sources.kexp.parse import playlist_url


def play(number: int, airdate: str, **fields: object) -> dict[str, object]:
    defaults = {"artist": "Band", "song": "Song", "album": "Record", "play_type": "trackplay"}
    return {"id": number, "airdate": airdate, "show": 10, **defaults, **fields}


PLAYS = [
    play(1, "2026-09-15T23:23:19-07:00", comment="First fact.\n--\nSecond fact.\n\n"),
    play(2, "2025-01-02T00:05:00-08:00", show=None, comment="First fact."),
    play(3, "2025-01-01T12:00:00-08:00", song="Song (Dub Mix)"),
    play(4, "2025-01-01T11:00:00-08:00", play_type="airbreak", artist=None, song=None),
]
SHOW = {"id": 10, "program_name": "Variety Mix", "host_names": ["Atticus"]}


def make(
    plays: list[dict[str, object]] | None = None,
    seen: list[httpx.Request] | None = None,
) -> KexpAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/v2/shows/10/":
            return httpx.Response(200, content=json.dumps(SHOW).encode())
        results = PLAYS if plays is None else plays
        return httpx.Response(200, content=json.dumps({"results": results}).encode())

    config = SourcesConfig.model_validate(
        {"kexp": {"rate": 1000}, "http": {"retries": 0, "escalation": "none"}},
    )
    return KexpAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


def context(kind: EntityKind, *ids: tuple[IdKind, str]) -> LookupContext:
    query = parse_query("Band - Song" if kind is EntityKind.TRACK else "Band - Record", kind)
    sources = [Provenance(source="musicbrainz")]
    identity = Identity(external_ids=[ExternalId(kind=k, value=v, sources=sources) for k, v in ids])
    return LookupContext(query=query, identity=identity)


@pytest.mark.asyncio
async def test_track_plays_by_recording_id() -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen=seen)
    found = context(EntityKind.TRACK, (IdKind.MUSICBRAINZ_RECORDING, "rec"))

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    assert dict(seen[0].url.params) == {"recording_id": "rec", "limit": "25"}
    assert [r.url.path for r in seen[1:]] == ["/v2/shows/10/"]
    assert partial.candidate is not None
    assert (partial.candidate.artist, partial.candidate.title) == ("Band", "Song")
    assert partial.candidate.url == "https://www.kexp.org/playlist/2026/9/15/11pm/"
    assert {(r.kind, r.target.type) for r in partial.relations} == {
        (RelationKind.BROADCAST, EntityType.BROADCAST),
    }
    assert [(r.target.name, r.target.date, r.note) for r in partial.relations] == [
        ("KEXP: Variety Mix", "2026-09-15", "Atticus"),
        ("KEXP", "2025-01-02", None),
    ]
    assert [(t.kind, t.body, t.author, t.publication, t.scope) for t in partial.texts] == [
        (TextKind.BROADCAST, "First fact.", "Atticus", "KEXP: Variety Mix", Scope.RECORDING),
        (TextKind.BROADCAST, "Second fact.", "Atticus", "KEXP: Variety Mix", Scope.RECORDING),
        (TextKind.BROADCAST, "First fact.", None, "KEXP", Scope.RECORDING),
    ]


@pytest.mark.asyncio
async def test_track_plays_by_text() -> None:
    seen: list[httpx.Request] = []
    found = context(EntityKind.TRACK)

    await make(seen=seen).lookup(found.query, found)

    assert dict(seen[0].url.params) == {"artist": "Band", "song": "Song", "limit": "25"}


@pytest.mark.asyncio
async def test_album_plays_by_text_even_with_a_release_group_id() -> None:
    seen: list[httpx.Request] = []
    found = context(EntityKind.ALBUM, (IdKind.MUSICBRAINZ_RELEASE_GROUP, "rg"))

    partial = await make(seen=seen).lookup(found.query, found)

    assert dict(seen[0].url.params) == {"artist": "Band", "album": "Record", "limit": "25"}
    assert partial.candidate is not None
    assert partial.candidate.title == "Record"
    assert {r.scope for r in partial.relations} == {Scope.RELEASE_GROUP}
    assert len(partial.relations) == 3


@pytest.mark.asyncio
async def test_no_plays_of_the_record() -> None:
    found = context(EntityKind.TRACK)
    url_query = parse_query("https://www.discogs.com/master/1-Band-Song")

    with pytest.raises(NotFoundError, match="no KEXP plays"):
        await make([play(5, "2025-01-01T11:00:00-08:00", artist="Somebody Else")]).lookup(
            found.query,
            found,
        )
    with pytest.raises(NotFoundError, match="name the record"):
        await make().lookup(url_query, LookupContext(query=url_query))


@pytest.mark.parametrize(
    ("airdate", "page"),
    [
        ("2026-01-05T00:30:00-08:00", "2026/1/5/12am"),
        ("2026-01-05T12:30:00-08:00", "2026/1/5/12pm"),
        ("2026-01-05T09:30:00-08:00", "2026/1/5/9am"),
    ],
)
def test_playlist_url(airdate: str, page: str) -> None:
    assert playlist_url(airdate) == f"https://www.kexp.org/playlist/{page}/"
