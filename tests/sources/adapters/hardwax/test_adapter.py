import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from deadwax.core import (
    BlockedError,
    EntityKind,
    EntityType,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Query,
    RelationKind,
    Scope,
    SourceError,
    TagKind,
    TextKind,
    merge,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.hardwax import HardWaxAdapter

# Search feeds and product pages fetched on 2026-11-13; pages keep their meta tags and article.
PAGES = Path(__file__).resolve().parents[3] / "fixtures" / "hardwax" / "pages"

SITE = "https://hardwax.com"
FEED = f"{SITE}/feeds/search.json"
UNTRUE = f"{SITE}/55357/burial/untrue/"
PHONEGLOW = f"{SITE}/88197/burial-and-kode9/phoneglow-eyes-go-blank/"
SERVED = {
    UNTRUE: "release_55357.html",
    PHONEGLOW: "release_88197.html",
    f"{SITE}/25738/various-artists/hyperswim/": "release_25738.html",
}
SEARCHES = {
    "Burial Untrue": "search_burial_untrue.json",
    "Burial Archangel": "search_burial_archangel.json",
    "Burial Phoneglow": "search_burial_phoneglow.json",
}
NOW = datetime(2026, 11, 13, tzinfo=UTC)


def feed(*items: dict[str, str]) -> str:
    return json.dumps({"version": "https://jsonfeed.org/version/1.1", "items": list(items)})


def make(
    pages: dict[str, str] | None = None,
    status: int = 200,
) -> tuple[HardWaxAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, headers={"cf-mitigated": "challenge"})
        url = str(request.url).split("?", maxsplit=1)[0]
        if pages is not None and url in pages:
            return httpx.Response(200, text=pages[url])
        if url == FEED and request.url.params["find"] in SEARCHES:
            return httpx.Response(
                200,
                content=(PAGES / SEARCHES[request.url.params["find"]]).read_bytes(),
            )
        if url in SERVED:
            return httpx.Response(200, content=(PAGES / SERVED[url]).read_bytes())
        return httpx.Response(404)

    config = SourcesConfig.model_validate(
        {"hardwax": {"rate": 1000}, "http": {"retries": 0, "escalation": []}},
    )
    return HardWaxAdapter(config, HttpResources(transport=httpx.MockTransport(handler))), seen


async def looked_up(
    adapter: HardWaxAdapter,
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
async def test_release_by_search_with_shop_text_and_label() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.ALBUM))

    assert urls(seen) == [FEED, UNTRUE]
    assert seen[1].url.query == b""
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.artist, candidate.title, candidate.url) == (
        EntityKind.ALBUM,
        "Burial",
        "Untrue",
        UNTRUE,
    )
    assert [(label.name, label.catalog_number) for label in candidate.labels] == [
        ("Hyperdub", "HDB LP 002"),
    ]
    assert [(t.kind, t.body, t.publication, t.scope) for t in partial.texts] == [
        (
            TextKind.SHOP,
            "Timeless definition of leftfield UKG, a modern classic",
            "Hard Wax",
            Scope.RELEASE,
        ),
    ]
    assert partial.tags == []
    assert [(link.service, link.url, link.target) for link in partial.links] == [
        ("hardwax", UNTRUE, LinkTarget.ALBUM),
    ]


@pytest.mark.asyncio
async def test_track_is_found_in_the_tracklist_of_its_release() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query("Burial - Archangel", EntityKind.TRACK))

    assert urls(seen) == [FEED, UNTRUE]
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.artist, candidate.title) == (
        EntityKind.TRACK,
        "Burial",
        "Archangel",
    )
    assert [(r.kind, r.target.type, r.target.name, r.target.url) for r in partial.relations] == [
        (RelationKind.APPEARS_ON, EntityType.RELEASE, "Untrue", UNTRUE),
    ]
    assert [t.scope for t in partial.texts] == [Scope.RELEASE]


@pytest.mark.asyncio
async def test_track_of_a_split_release_names_its_own_artist() -> None:
    adapter, _ = make()

    partial = await looked_up(adapter, parse_query("Burial - Phoneglow", EntityKind.TRACK))

    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.artist, candidate.title) == ("Burial", "Phoneglow")
    assert partial.relations[0].target.artist == "Burial and Kode9"


@pytest.mark.asyncio
async def test_another_mix_is_kept_out_of_the_record() -> None:
    remixes = f"{SITE}/3/burial/archangel-remixes/"
    listing = feed(
        {
            "title": "Burial: Archangel Remixes",
            "url": remixes,
            "content_html": "<ol><li>Archangel (Kode9 Remix)</li></ol>",
        },
    )
    page = (
        '<div id="record-3"><h2>Burial: Archangel Remixes</h2><p>Dubbed out</p>'
        '<div id="track-3_A"><a title="Burial: Archangel (Kode9 Remix)">A</a></div></div>'
    )
    adapter, seen = make(pages={FEED: listing, remixes: page})
    query = parse_query("Burial - Archangel", EntityKind.TRACK)

    partial = await looked_up(adapter, query)
    dossier = merge(query, [partial], generated_at=NOW)

    assert urls(seen) == [FEED, remixes]
    assert dossier.texts == []
    assert [(r.kind, r.target.name) for r in dossier.relations] == [
        (RelationKind.OTHER_VERSION, "Archangel (Kode9 Remix)"),
    ]
    assert [d.field for d in dossier.identity.discrepancies] == ["version"]


@pytest.mark.asyncio
async def test_release_url_is_read_without_searching() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query(f"{UNTRUE}?focus=download"))

    assert urls(seen) == [UNTRUE]
    assert partial.candidate is not None
    assert partial.candidate.url == UNTRUE


@pytest.mark.asyncio
async def test_page_found_by_earlier_passes() -> None:
    adapter, seen = make()
    query = parse_query("Burial - Untrue", EntityKind.ALBUM)
    link = Link(service="hardwax", url=UNTRUE, target=LinkTarget.ALBUM, sources=[])

    await looked_up(adapter, query, LookupContext(query=query, links=[link]))

    assert urls(seen) == [UNTRUE]


@pytest.mark.asyncio
async def test_store_sections_are_genres_except_catalogue_ones() -> None:
    page = (
        '<div id="record-1"><a href="/label/hyperdub/">Hyperdub</a> <a href="/1/x/">HDB 1</a>'
        '<a href="/section/electronic/">Electronic</a><a href="/section/labels/">Label Catalog</a>'
        '<a href="/section/electronic/">Electronic</a>'
        "<h2><span>Burial:</span> <span>Untrue</span></h2><p>Shop <em>line</em></p></div>"
    )
    adapter, _ = make(pages={UNTRUE: page})

    partial = await looked_up(adapter, parse_query(UNTRUE))

    assert [(t.name, t.kind) for t in partial.tags] == [("Electronic", TagKind.GENRE)]
    assert [t.body for t in partial.texts] == ["Shop line"]


@pytest.mark.asyncio
async def test_release_without_label_or_text() -> None:
    page = '<div id="record-1"><h2>Burial: Untrue</h2></div>'
    adapter, _ = make(pages={UNTRUE: page})

    partial = await looked_up(adapter, parse_query(UNTRUE))

    assert partial.candidate is not None
    assert partial.candidate.labels == []
    assert partial.texts == []


@pytest.mark.asyncio
async def test_track_missing_from_the_release_page() -> None:
    listing = feed(
        {
            "title": "Burial: Untrue",
            "url": f"{UNTRUE}?focus=download",
            "content_html": "<ol><li>Kindred</li><li>Unnamed: </li></ol>",
        },
        {"title": "No separator", "url": f"{SITE}/2/x/"},
    )
    adapter, _ = make(pages={FEED: listing})

    with pytest.raises(NotFoundError, match="does not list the track"):
        await looked_up(adapter, parse_query("Burial - Kindred", EntityKind.TRACK))


@pytest.mark.asyncio
async def test_no_matching_result() -> None:
    adapter, _ = make(pages={FEED: feed()})

    with pytest.raises(NotFoundError, match="no matching hardwax"):
        await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.ALBUM))


@pytest.mark.asyncio
async def test_challenge_is_blocked() -> None:
    adapter, _ = make(status=403)

    with pytest.raises(BlockedError):
        await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.ALBUM))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pages", "message"),
    [
        ({FEED: "<html>maintenance</html>"}, "not valid JSON Feed"),
        ({UNTRUE: "<html><body>Gone</body></html>"}, "names no release"),
        ({UNTRUE: '<div id="record-1"><h2>Untrue</h2></div>'}, "names no release"),
    ],
)
async def test_unreadable_responses(pages: dict[str, str], message: str) -> None:
    adapter, _ = make(pages=pages)
    query = parse_query(UNTRUE) if FEED not in pages else parse_query("A - B", EntityKind.ALBUM)

    with pytest.raises(SourceError, match=message):
        await looked_up(adapter, query)
