import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from deadwax.core import (
    BlockedError,
    EntityKind,
    EntityType,
    IdKind,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Provenance,
    Query,
    RelationKind,
    Scope,
    SourceError,
    TagKind,
    VersionKind,
    merge,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.beatport import BeatportAdapter, models
from deadwax.sources.beatport import parse as p

# Pages saved from a browser on 2026-11-13 and trimmed by scripts/saved_pages.py.
PAGES = Path(__file__).resolve().parent.parent / "fixtures" / "beatport" / "pages"

SITE = "https://www.beatport.com"
REMIX_EDIT = f"{SITE}/track/missing/1331132"
RADIO_EDIT = f"{SITE}/track/missing/27201133"
NOTHING_LEFT = f"{SITE}/release/nothing-left-to-lose/4075859"
YOUNG_AND_DUMB = f"{SITE}/release/young-and-dumb/7657829"
SERVED = {
    REMIX_EDIT: "track_1331132",
    RADIO_EDIT: "track_27201133",
    NOTHING_LEFT: "release_4075859",
    YOUNG_AND_DUMB: "release_7657829",
    f"{SITE}/search/tracks": "search_tracks",
    f"{SITE}/search/releases": "search_releases",
}
NOW = datetime(2026, 11, 13, tzinfo=UTC)


def state_page(props: dict[str, object]) -> str:
    state = json.dumps({"props": {"pageProps": props}})
    return f'<script id="__NEXT_DATA__" type="application/json">{state}</script>'


def make(
    pages: dict[str, str] | None = None,
    status: int = 200,
) -> tuple[BeatportAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, headers={"cf-mitigated": "challenge"})
        url = str(request.url).split("?", maxsplit=1)[0]
        if pages is not None and url in pages:
            return httpx.Response(200, text=pages[url])
        if url in SERVED:
            return httpx.Response(200, content=(PAGES / f"{SERVED[url]}.html").read_bytes())
        return httpx.Response(404)

    config = SourcesConfig.model_validate(
        {"beatport": {"rate": 1000}, "http": {"retries": 0, "escalation": []}},
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


def urls(seen: list[httpx.Request]) -> list[str]:
    return [str(request.url).split("?", maxsplit=1)[0] for request in seen]


@pytest.mark.asyncio
async def test_track_by_search_with_tempo_key_genre_and_charts() -> None:
    adapter, seen = make()
    query = parse_query(
        "Everything but the Girl - Missing (Todd Terry Remix - Radio Edit)",
        EntityKind.TRACK,
    )

    partial = await looked_up(adapter, query)

    assert urls(seen) == [f"{SITE}/search/tracks", RADIO_EDIT]
    assert seen[0].url.params["q"] == (
        "Everything but the Girl Missing (Todd Terry Remix - Radio Edit)"
    )
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.artist, candidate.title) == (
        "Everything But The Girl",
        "Missing (Todd Terry Remix - Radio Edit)",
    )
    assert candidate.version is not None
    assert candidate.version.kind is VersionKind.REMIX
    assert (candidate.bpm, candidate.key, candidate.date) == (124, "A Minor", "2002-01-01")
    assert candidate.isrcs == ["GBAHT0109010"]
    assert [(label.name, label.catalog_number) for label in candidate.labels] == [
        ("Virgin Records", "542 6165"),
    ]
    assert candidate.ids == {IdKind.BEATPORT_TRACK: "27201133"}
    assert [(tag.name, tag.kind) for tag in partial.tags] == [("Pop", TagKind.GENRE)]
    assert [
        (r.kind, r.target.type, r.target.name, r.target.artist, r.target.date, r.target.url)
        for r in partial.relations
    ] == [
        (
            RelationKind.CHARTED_BY,
            EntityType.CHART,
            "Pete Tong | Creamfields | Aug 2026",
            "Pete Tong",
            "2026-11-11",
            f"{SITE}/chart/pete-tong-creamfields-aug-2026/908621",
        ),
        (
            RelationKind.CHARTED_BY,
            EntityType.CHART,
            "2026 September - Hot Indian Summer Traxx",
            "Thomas Bogdan",
            "2026-09-02",
            f"{SITE}/chart/2026-september-hot-indian-summer-traxx/901380",
        ),
    ]
    assert partial.links == [
        Link(
            service="beatport",
            url=RADIO_EDIT,
            target=LinkTarget.TRACK,
            sources=[Provenance(source="beatport", url=RADIO_EDIT)],
        ),
    ]


@pytest.mark.asyncio
async def test_another_mix_is_kept_out_of_the_record() -> None:
    adapter, seen = make()
    query = parse_query("Everything but the Girl - Missing (Todd Terry Remix)", EntityKind.TRACK)

    partial = await looked_up(adapter, query)
    dossier = merge(query, [partial], generated_at=NOW)

    # The page lists no full Todd Terry Remix; the first other version is read instead.
    assert urls(seen)[1:] == [REMIX_EDIT]
    assert dossier.identity.bpm is None
    assert dossier.tags == []
    [relation] = dossier.relations
    assert relation.kind is RelationKind.OTHER_VERSION
    assert relation.target.url == REMIX_EDIT
    assert [d.field for d in dossier.identity.discrepancies] == ["version"]


@pytest.mark.asyncio
async def test_remixers_are_credits_not_artists() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query(REMIX_EDIT))

    assert urls(seen) == [REMIX_EDIT]
    assert partial.candidate is not None
    assert partial.candidate.artist == "Everything But The Girl"
    assert [(c.role, c.name, c.scope) for c in partial.credits] == [
        ("remixer", "CL McSpadden", Scope.RECORDING),
    ]
    assert partial.relations == []


@pytest.mark.asyncio
async def test_release_by_search() -> None:
    adapter, seen = make()
    query = parse_query("Everything but the Girl - Nothing Left To Lose", EntityKind.ALBUM)

    partial = await looked_up(adapter, query)

    assert urls(seen) == [f"{SITE}/search/releases", NOTHING_LEFT]
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.artist, candidate.title, candidate.date) == (
        EntityKind.ALBUM,
        "Everything But The Girl",
        "Nothing Left To Lose",
        "2023-03-29",
    )
    assert candidate.upcs == ["00044003356849"]
    assert candidate.ids == {IdKind.BEATPORT_RELEASE: "4075859"}
    assert [(c.name, c.scope) for c in partial.credits] == [("Four Tet", Scope.RELEASE)]
    assert [link.target for link in partial.links] == [LinkTarget.ALBUM]


@pytest.mark.asyncio
async def test_release_url_is_read_without_searching() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query(YOUNG_AND_DUMB))

    assert urls(seen) == [YOUNG_AND_DUMB]
    assert partial.candidate is not None
    assert partial.candidate.labels[0].name == "Everything But The Girl"


@pytest.mark.asyncio
async def test_page_found_by_earlier_passes() -> None:
    adapter, seen = make()
    query = parse_query("Everything but the Girl - Missing", EntityKind.TRACK)
    link = Link(service="beatport", url=RADIO_EDIT, target=LinkTarget.TRACK, sources=[])

    await looked_up(adapter, query, LookupContext(query=query, links=[link]))

    assert urls(seen) == [RADIO_EDIT]


@pytest.mark.asyncio
async def test_no_matching_result() -> None:
    adapter, _ = make()

    with pytest.raises(NotFoundError, match="no matching beatport"):
        await looked_up(adapter, parse_query("Burial - Archangel", EntityKind.TRACK))


@pytest.mark.asyncio
async def test_search_page_without_results() -> None:
    adapter, _ = make(pages={f"{SITE}/search/tracks": state_page({})})

    with pytest.raises(NotFoundError):
        await looked_up(adapter, parse_query("Burial - Archangel", EntityKind.TRACK))


@pytest.mark.asyncio
async def test_challenge_is_blocked() -> None:
    adapter, _ = make(status=403)

    with pytest.raises(BlockedError):
        await looked_up(adapter, parse_query("Burial - Archangel", EntityKind.TRACK))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("<html></html>", "required page state missing"),
        ('<script id="__NEXT_DATA__">{not json</script>', "not valid JSON"),
        ('<script id="__NEXT_DATA__">[]</script>', "no page properties"),
        (state_page({"chartPosition": None}), "neither a track nor a release"),
        (state_page({"track": {"track_id": 1}}), "unexpected Beatport page state"),
    ],
)
async def test_unreadable_page(content: str, message: str) -> None:
    adapter, _ = make(pages={REMIX_EDIT: content})

    with pytest.raises(SourceError, match=message):
        await looked_up(adapter, parse_query(REMIX_EDIT))


def test_unreadable_page_state_is_traced(
    traced: Callable[[str], list[dict[str, object]]],
) -> None:
    state = '{"props": {"pageProps": {"track":'
    content = f'<script id="__NEXT_DATA__">{state}</script>'.encode()

    with pytest.raises(SourceError, match="not valid JSON"):
        p.page_props(content, "https://www.beatport.com/track/x/1")

    [event] = traced("parse.unrecognized")
    assert event["length"] == len(state)
    assert event["tail"] == state


def test_search_results_of_another_shape_give_no_hits() -> None:
    query = {"queryKey": ["search-tracks"], "state": {"data": {"data": 1}}}
    other = {"queryKey": ["search-releases"], "state": {"data": {"data": [{"release_id": 1}]}}}

    assert p.track_hits({"dehydratedState": {"queries": [query, "x"]}}) == []
    assert p.release_hits({"dehydratedState": {"queries": [other]}}) == []
    assert p.release_hits({"dehydratedState": {"queries": {}}}) == []


def test_chart_owner_and_slug() -> None:
    by_person = models.Chart(id=1, name="Mix", person=models.ChartOwner(owner_name="DJ"))

    assert p.chart_owner(by_person) == "DJ"
    assert p.chart_owner(models.Chart(id=2, name="Mix")) is None
    assert p.chart_url(models.Chart(id=3, name="Best Of 2026!")) == f"{SITE}/chart/best-of-2026/3"
    assert p.slug("Buzzin' Fly") == "buzzin-fly"
    assert p.slug("!!!") == "-"


def test_genres_of_search_results_and_track_pages() -> None:
    hit = models.Track.model_validate(
        {
            "track_id": 1,
            "track_name": "Untitled",
            "mix_name": "Part 2",
            "genre": [{"genre_name": "House"}, {"genre_name": None}],
        },
    )
    page = models.Track.model_validate(
        {"id": 2, "name": "Plain", "genre": {"name": "House", "sub_genre": {"name": "Soulful"}}},
    )

    assert [tag.name for tag in p.track_partial(hit, models.Charts(), "u").tags] == ["House"]
    assert p.mix_version(hit.mix_name) is None
    assert p.track_title(page) == "Plain"
    assert [(t.name, t.kind) for t in p.track_partial(page, models.Charts(), "u").tags] == [
        ("House", TagKind.GENRE),
        ("Soulful", TagKind.STYLE),
    ]
