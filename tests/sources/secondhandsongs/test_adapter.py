import json
from datetime import UTC, datetime

import httpx
import pytest

from deadwax.core import (
    EntityKind,
    EntityType,
    LookupContext,
    NotFoundError,
    RelationKind,
    Scope,
    merge,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.secondhandsongs import SecondHandSongsAdapter
from deadwax.sources.secondhandsongs.parse import website

API = "https://api.secondhandsongs.com"


def ref(number: int, title: str, performer: str, *, original: bool) -> dict[str, object]:
    return {
        "uri": f"{API}/performance/{number}",
        "title": title,
        "performer": {"name": performer},
        "isOriginal": original,
    }


WORK = {"uri": f"{API}/work/1", "title": "Song"}
ROUTES: dict[str, object] = {
    "/search/performance": {
        "resultPage": [
            {"uri": f"{API}/performance/9", "title": "Song"},
            ref(8, "Other Song", "Band", original=True),
            ref(1, "Song", "Band", original=True),
        ],
    },
    "/performance/1": {
        **ref(1, "Song", "Band", original=True),
        "firstReleaseDate": "1970-11",
        "works": [WORK],
        "covers": [ref(2, "Song", "Singer", original=False)],
    },
    "/performance/3": {
        **ref(3, "Song", "Singer", original=False),
        "date": "1999",
        "works": [WORK],
        "originals": [{**WORK, "original": ref(1, "Song", "Band", original=True)}],
    },
    "/performance/4": {
        **ref(4, "Song", "Band", original=False),
        "works": [WORK],
        "originals": [{**WORK, "original": ref(5, "Song", "Band", original=True)}],
    },
    "/performance/5": {
        **ref(5, "Song", "Band", original=True),
        "covers": [ref(2, "Song", "Singer", original=False)],
    },
    "/work/1": {
        **WORK,
        "credits": [{"commonName": "Writer"}],
        "basedOn": [{"uri": f"{API}/work/6", "title": "Old Tune"}],
        "derivedWorks": [{"uri": f"{API}/work/7", "title": "Canción"}],
    },
}


def make(
    routes: dict[str, object] | None = None,
    *,
    api_key: str | None = None,
    seen: list[httpx.Request] | None = None,
) -> SecondHandSongsAdapter:
    table = ROUTES | (routes or {})

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = table.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"error": {"code": 10001}})
        return httpx.Response(200, content=json.dumps(body).encode())

    config = SourcesConfig.model_validate(
        {
            "secondhandsongs": {"rate": 1000, "api_key": api_key},
            "http": {"retries": 0, "escalation": []},
        },
    )
    return SecondHandSongsAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


def search_for(number: int, title: str, performer: str) -> dict[str, object]:
    return {"/search/performance": {"resultPage": [ref(number, title, performer, original=False)]}}


TRACK = parse_query("Band - Song", EntityKind.TRACK)


@pytest.mark.asyncio
async def test_original_lists_covers_and_writers() -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen=seen)

    partial = await adapter.lookup(TRACK, LookupContext(query=TRACK))
    await adapter.aclose()

    assert seen[0].url.params["performer"] == "Band"
    assert seen[0].headers["accept"] == "application/json"
    assert "x-api-key" not in seen[0].headers
    assert partial.candidate is not None
    assert (partial.candidate.artist, partial.candidate.date) == ("Band", "1970-11")
    assert partial.candidate.url == "https://secondhandsongs.com/performance/1"
    assert [(c.role, c.name, c.scope) for c in partial.credits] == [
        ("writer", "Writer", Scope.WORK),
    ]
    found = [
        (r.kind, r.target.type, r.target.artist, r.target.name, r.note) for r in partial.relations
    ]
    assert found == [
        (RelationKind.COVERED_BY, EntityType.RECORDING, "Singer", "Song", None),
        (RelationKind.COVER_OF, EntityType.WORK, None, "Old Tune", "adaptation"),
        (RelationKind.COVERED_BY, EntityType.WORK, None, "Canción", "adaptation"),
    ]  # fmt: skip


@pytest.mark.asyncio
async def test_cover_names_the_work_and_the_dated_original() -> None:
    adapter = make(search_for(3, "Song", "Singer"))
    query = parse_query("Singer - Song", EntityKind.TRACK)

    partial = await adapter.lookup(query, LookupContext(query=query))

    assert partial.candidate is not None
    assert partial.candidate.date == "1999"
    cover_of = [r for r in partial.relations if r.note != "adaptation"]
    assert [(r.kind, r.target.type, r.target.artist, r.target.date, r.note) for r in cover_of] == [
        (RelationKind.COVER_OF, EntityType.WORK, None, None, None),
        (RelationKind.COVER_OF, EntityType.RECORDING, "Band", "1970-11", "original"),
    ]


@pytest.mark.asyncio
async def test_later_version_by_the_original_artist_shares_the_covers() -> None:
    seen: list[httpx.Request] = []
    adapter = make(search_for(4, "Song", "Band"), api_key="s3cret", seen=seen)

    partial = await adapter.lookup(TRACK, LookupContext(query=TRACK))

    assert seen[0].headers["x-api-key"] == "s3cret"
    kinds = [(r.kind, r.target.artist, r.note) for r in partial.relations if r.note != "adaptation"]
    assert kinds == [
        (RelationKind.OTHER_VERSION, "Band", "first performance"),
        (RelationKind.COVERED_BY, "Singer", None),
    ]


@pytest.mark.asyncio
async def test_album_contributes_nothing() -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen=seen)
    album = parse_query("Band - Record", EntityKind.ALBUM)

    partial = await adapter.lookup(album, LookupContext(query=album))

    assert partial.model_dump(exclude={"source"}) == {
        "candidate": None, "tags": [], "credits": [], "texts": [], "relations": [],
        "metrics": [], "links": [], "errors": [],
    }  # fmt: skip
    assert seen == []


@pytest.mark.asyncio
async def test_not_found() -> None:
    url_query = parse_query("https://www.discogs.com/master/1-Band-Song")

    with pytest.raises(NotFoundError, match="name the record"):
        await make().lookup(url_query, LookupContext(query=url_query))
    with pytest.raises(NotFoundError, match="no matching"):
        await make({"/search/performance": {"resultPage": []}}).lookup(
            TRACK,
            LookupContext(query=TRACK),
        )
    with pytest.raises(NotFoundError):
        await make(search_for(404, "Song", "Band")).lookup(TRACK, LookupContext(query=TRACK))


@pytest.mark.asyncio
async def test_other_version_is_not_merged() -> None:
    adapter = make(
        search_for(3, "Song (Live)", "Band")
        | {"/performance/3": {**ref(3, "Song (Live)", "Band", original=False), "works": [WORK]}},
    )

    partial = await adapter.lookup(TRACK, LookupContext(query=TRACK))
    dossier = merge(TRACK, [partial], generated_at=datetime.now(UTC))

    assert dossier.credits == []
    assert [r.kind for r in dossier.relations] == [RelationKind.OTHER_VERSION]
    assert [d.field for d in dossier.identity.discrepancies] == ["version"]


def test_website_keeps_foreign_urls() -> None:
    assert website("https://example.com/x") == "https://example.com/x"
