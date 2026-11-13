import json
from datetime import UTC, datetime

import httpx
import pytest

from deadwax.core import (
    BlockedError,
    EntityKind,
    IdKind,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Provenance,
    Query,
    RelationKind,
    SourceError,
    TagKind,
    VersionKind,
    merge,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.beatport import BeatportAdapter, parse

SITE = "https://www.beatport.com"
ORIGINAL_URL = f"{SITE}/track/missing/1"
EXTENDED_URL = f"{SITE}/track/missing/2"
RELEASE_URL = f"{SITE}/release/missing-remixes/10"

ARTIST = {"id": 5, "name": "Everything but the Girl", "slug": "everything-but-the-girl"}
RELEASE = {
    "id": 10,
    "name": "Missing (Remixes)",
    "slug": "missing-remixes",
    "label": {"id": 3, "name": "Blanco y Negro"},
}
ORIGINAL = {
    "id": 1,
    "name": "Missing",
    "mix_name": "Todd Terry Remix",
    "slug": "missing",
    "bpm": 124,
    "key": {"name": "A Minor", "camelot_number": 8, "camelot_letter": "A"},
    "isrc": "GBAHT9500001",
    "genre": {"id": 5, "name": "House"},
    "sub_genre": {"id": 51, "name": "Deep House"},
    "artists": [ARTIST],
    "remixers": [{"id": 6, "name": "Todd Terry"}],
    "release": RELEASE | {"catalog_number": "NEG84CD"},
    "publish_date": "1995-10-02",
}
EXTENDED = ORIGINAL | {"id": 2, "mix_name": "Todd Terry Extended Remix", "bpm": 125}

# Search results use the search service's field names.
SEARCH_ORIGINAL = {
    "track_id": 1,
    "track_name": "Missing",
    "mix_name": "Todd Terry Remix",
    "slug": "missing",
    "artists": [{"artist_id": 5, "artist_name": "Everything but the Girl"}],
    "genre": [{"genre_id": 5, "genre_name": "House"}],
    "key_name": "A Minor",
    "bpm": 124,
}
SEARCH_RELEASE = {
    "release_id": 10,
    "release_name": "Missing (Remixes)",
    "slug": "missing-remixes",
    "catalog_number": "NEG84CD",
    "artists": [{"artist_id": 5, "artist_name": "Everything but the Girl"}],
}
NOW = datetime(2026, 11, 13, tzinfo=UTC)


def page(page_props: dict[str, object]) -> str:
    state = json.dumps({"props": {"pageProps": page_props}})
    script = f'<script id="__NEXT_DATA__" type="application/json">{state}</script>'
    return f"<html><body>{script}</body></html>"


def search(*results: dict[str, object]) -> str:
    query = {"queryKey": ["search"], "state": {"data": {"data": list(results)}}}
    return page({"dehydratedState": {"queries": [query]}})


PAGES = {
    ORIGINAL_URL: page({"track": ORIGINAL}),
    EXTENDED_URL: page({"track": EXTENDED}),
    RELEASE_URL: page(
        {
            "release": RELEASE
            | {"catalog_number": "NEG84CD", "upc": "0075678723421", "artists": [ARTIST]},
            "dehydratedState": {
                "queries": [{"state": {"data": {"results": [ORIGINAL, EXTENDED]}}}],
            },
        },
    ),
}


def make(
    tracks: str | None = None,
    pages: dict[str, str] | None = None,
    status: int = 200,
) -> tuple[BeatportAdapter, list[str]]:
    seen: list[str] = []
    served = PAGES | (pages or {})

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if status != 200:
            return httpx.Response(status, headers={"cf-mitigated": "challenge"})
        if request.url.path == "/search/tracks":
            return httpx.Response(
                200,
                text=tracks if tracks is not None else search(SEARCH_ORIGINAL),
            )
        if request.url.path == "/search/releases":
            return httpx.Response(200, text=search(SEARCH_RELEASE))
        found = served.get(url.split("?", maxsplit=1)[0])
        return httpx.Response(200, text=found) if found is not None else httpx.Response(404)

    config = SourcesConfig.model_validate(
        {"beatport": {"rate": 1000}, "http": {"retries": 0, "escalation": "none"}},
    )
    return BeatportAdapter(config, HttpResources(transport=httpx.MockTransport(handler))), seen


async def looked_up(
    adapter: BeatportAdapter,
    query: Query,
    context: LookupContext | None = None,
) -> Partial:
    try:
        return await adapter.lookup(query, context or LookupContext(query=query))
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_track_by_search_reads_tempo_key_genres_and_remixers() -> None:
    adapter, seen = make()
    query = parse_query("Everything but the Girl - Missing (Todd Terry Remix)", EntityKind.TRACK)

    partial = await looked_up(adapter, query)

    assert seen[0].startswith(f"{SITE}/search/tracks?q=Everything")
    assert seen[1:] == [ORIGINAL_URL]
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.artist, candidate.title) == (
        "Everything but the Girl",
        "Missing (Todd Terry Remix)",
    )
    assert candidate.version is not None
    assert (candidate.version.kind, candidate.version.detail) == (
        VersionKind.REMIX,
        "Todd Terry Remix",
    )
    assert (candidate.bpm, candidate.key) == (124, "A Minor")
    assert candidate.isrcs == ["GBAHT9500001"]
    assert [(label.name, label.catalog_number) for label in candidate.labels] == [
        ("Blanco y Negro", "NEG84CD"),
    ]
    assert candidate.date == "1995-10-02"
    assert candidate.ids == {IdKind.BEATPORT_TRACK: "1"}
    assert [(tag.name, tag.kind) for tag in partial.tags] == [
        ("House", TagKind.GENRE),
        ("Deep House", TagKind.STYLE),
    ]
    assert [(credit.role, credit.name) for credit in partial.credits] == [("remixer", "Todd Terry")]
    assert partial.links == [
        Link(
            service="beatport",
            url=ORIGINAL_URL,
            target=LinkTarget.TRACK,
            sources=[Provenance(source="beatport", url=ORIGINAL_URL)],
        ),
    ]


@pytest.mark.asyncio
async def test_extended_mix_found_for_another_mix_is_kept_out_of_the_record() -> None:
    extended_hit = SEARCH_ORIGINAL | {"track_id": 2, "mix_name": "Todd Terry Extended Remix"}
    adapter, seen = make(tracks=search(extended_hit))
    query = parse_query("Everything but the Girl - Missing (Todd Terry Remix)", EntityKind.TRACK)

    partial = await looked_up(adapter, query)
    dossier = merge(query, [partial], generated_at=NOW)

    assert seen[1:] == [EXTENDED_URL]
    assert dossier.identity.bpm is None
    assert dossier.tags == []
    [relation] = dossier.relations
    assert relation.kind is RelationKind.OTHER_VERSION
    assert relation.target.url == EXTENDED_URL
    assert [d.field for d in dossier.identity.discrepancies] == ["version"]


@pytest.mark.asyncio
async def test_extended_mix_versus_original_mix() -> None:
    original = SEARCH_ORIGINAL | {"track_id": 3, "mix_name": "Original Mix"}
    extended = SEARCH_ORIGINAL | {"track_id": 4, "mix_name": "Extended Mix"}
    pages = {
        f"{SITE}/track/missing/3": page(
            {"track": ORIGINAL | {"id": 3, "mix_name": "Original Mix", "remixers": []}},
        ),
        f"{SITE}/track/missing/4": page(
            {"track": ORIGINAL | {"id": 4, "mix_name": "Extended Mix", "remixers": []}},
        ),
    }
    adapter, seen = make(tracks=search(extended, original), pages=pages)
    query = parse_query("Everything but the Girl - Missing", EntityKind.TRACK)

    partial = await looked_up(adapter, query)

    assert seen[1:] == [f"{SITE}/track/missing/3"]
    assert partial.candidate is not None
    assert partial.candidate.version is not None
    assert partial.candidate.version.kind is VersionKind.ORIGINAL


@pytest.mark.asyncio
async def test_track_url_is_read_without_searching() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query(EXTENDED_URL))

    assert seen == [EXTENDED_URL]
    assert partial.candidate is not None
    assert partial.candidate.bpm == 125


@pytest.mark.asyncio
async def test_page_found_by_earlier_passes() -> None:
    adapter, seen = make()
    query = parse_query("Everything but the Girl - Missing (Todd Terry Remix)", EntityKind.TRACK)
    link = Link(service="beatport", url=ORIGINAL_URL, target=LinkTarget.TRACK, sources=[])

    await looked_up(adapter, query, LookupContext(query=query, links=[link]))

    assert seen == [ORIGINAL_URL]


@pytest.mark.asyncio
async def test_release_by_search() -> None:
    adapter, seen = make()
    query = parse_query("Everything but the Girl - Missing (Remixes)", EntityKind.ALBUM)

    partial = await looked_up(adapter, query)

    assert seen[0].startswith(f"{SITE}/search/releases?q=")
    assert seen[1:] == [RELEASE_URL]
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.title, candidate.bpm) == (
        EntityKind.ALBUM,
        "Missing (Remixes)",
        None,
    )
    assert candidate.upcs == ["0075678723421"]
    assert candidate.ids == {IdKind.BEATPORT_RELEASE: "10"}
    assert [tag.name for tag in partial.tags] == ["House", "Deep House"]
    assert [link.target for link in partial.links] == [LinkTarget.ALBUM]


@pytest.mark.asyncio
async def test_no_matching_result() -> None:
    adapter, _ = make(tracks=search())
    query = parse_query("Burial - Archangel", EntityKind.TRACK)

    with pytest.raises(NotFoundError, match="no matching beatport"):
        await looked_up(adapter, query)


@pytest.mark.asyncio
async def test_challenge_is_blocked() -> None:
    adapter, _ = make(status=403)
    query = parse_query("Burial - Archangel", EntityKind.TRACK)

    with pytest.raises(BlockedError):
        await looked_up(adapter, query)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("<html></html>", "no __NEXT_DATA__"),
        ('<script id="__NEXT_DATA__">{not json</script>', "not valid JSON"),
        (
            page({"track": {"id": 9, "name": "Other", "mix_name": "Original Mix"}}),
            "does not list its track",
        ),
    ],
)
async def test_unreadable_track_page(content: str, message: str) -> None:
    adapter, _ = make(pages={ORIGINAL_URL: content})

    with pytest.raises(SourceError, match=message):
        await looked_up(adapter, parse_query(ORIGINAL_URL))


@pytest.mark.asyncio
async def test_release_page_without_a_release() -> None:
    adapter, _ = make(pages={RELEASE_URL: page({"tracks": [ORIGINAL | {"release": RELEASE}]})})

    with pytest.raises(SourceError, match="lists no release"):
        await looked_up(adapter, parse_query(RELEASE_URL))


def test_state_objects_of_other_shapes_are_skipped() -> None:
    state = {
        "a": [{"id": 1, "mix_name": "Original Mix"}, "text", None],
        "b": {"track_id": 2, "track_name": "Untitled", "mix_name": None, "genre": None},
        "c": {"id": 3, "name": "Plain", "mix_name": "", "key": None, "artists": [ARTIST]},
    }

    found = {track.id: track for track in parse.tracks(state)}

    assert sorted(found) == [2, 3]
    assert found[2].genres == []
    assert parse.track_title(found[3]) == "Plain"
    assert parse.mix_version(found[3].mix_name) is None
    assert parse.mix_version("Part 2") is None
    assert parse.track_partial(found[3], ORIGINAL_URL).candidate is not None


def test_fullest_copy_of_a_track_wins() -> None:
    short = {"id": 1, "name": "Missing", "mix_name": "Original Mix"}

    [track] = parse.tracks({"list": [short], "page": ORIGINAL | {"mix_name": "Original Mix"}})

    assert track.bpm == 124
