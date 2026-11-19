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
    VersionKind,
    merge,
)
from deadwax.sources import SourcesConfig, parse_query
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.juno import JunoAdapter
from deadwax.sources.adapters.juno import parse as p

# Pages saved from Firefox's view-source tab on 2026-11-13 and trimmed by scripts/saved_pages.py.
PAGES = Path(__file__).resolve().parents[3] / "fixtures" / "juno" / "pages"

SITE = "https://www.juno.co.uk"
SEARCH = f"{SITE}/search/"
UNTRUE = f"{SITE}/products/burial-untrue-vinyl/285827-01/"
MISSING_COLOURED = f"{SITE}/products/everything-but-the-girl-missing-vinyl/1105467-01/"
MISSING_BLACK = f"{SITE}/products/everything-but-the-girl-missing-vinyl/1105468-01/"
AMPLIFIED_HEART = (
    f"{SITE}/products/everything-but-the-amplified-heart-25th-anniversary-edition-vinyl/733799-01/"
)
SERVED = {
    UNTRUE: "product_285827",
    MISSING_COLOURED: "product_1105467",
    MISSING_BLACK: "product_1105468",
    AMPLIFIED_HEART: "product_733799",
}

# Searches answered with the saved results of a similar query.
SEARCHES = {
    "Burial Untrue": "search_burial_untrue",
    "Burial Archangel": "search_burial_untrue",
    "Everything but the Girl Missing": "search_missing",
    "Everything but the Girl Missing (Todd Terry Remix)": "search_missing",
}
NOW = datetime(2026, 11, 13, tzinfo=UTC)


def results(*items: tuple[str, str, str, list[str]]) -> str:
    rows = "".join(
        f'<div class="dv-item"><strong><a href="/artists/x/">{artist}</a></strong>'
        f'<a class="text-md" href="{href}">{title}</a>'
        + "".join(f'<div class="listing-track"><div></div><div>{t}</div></div>' for t in tracks)
        + "</div>"
        for artist, title, href, tracks in items
    )
    return f'<div class="product-list">{rows}</div>'


def make(
    pages: dict[str, str] | None = None,
    status: int = 200,
) -> tuple[JunoAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, headers={"cf-mitigated": "challenge"})
        url = str(request.url).split("?", maxsplit=1)[0]
        if pages is not None and url in pages:
            return httpx.Response(200, text=pages[url])
        name = SERVED.get(url)
        if url == SEARCH:
            name = SEARCHES.get(request.url.params["q[all][]"])
        if name is None:
            return httpx.Response(404)
        return httpx.Response(200, content=(PAGES / f"{name}.html").read_bytes())

    config = SourcesConfig.model_validate(
        {"juno": {"rate": 1000}, "http": {"retries": 0, "escalation": []}},
    )
    return JunoAdapter(config, HttpResources(transport=httpx.MockTransport(handler))), seen


async def looked_up(
    adapter: JunoAdapter,
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
async def test_release_by_search_with_review_label_and_date() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.ALBUM))

    assert urls(seen) == [SEARCH, UNTRUE]
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.artist, candidate.title, candidate.date, candidate.url) == (
        EntityKind.ALBUM,
        "BURIAL",
        "Untrue",
        "2007-11-02",
        UNTRUE,
    )
    assert [(label.name, label.catalog_number) for label in candidate.labels] == [
        ("Hyperdub", "HDBLP 002"),
    ]
    [text] = partial.texts
    assert (text.kind, text.publication, text.scope) == (TextKind.SHOP, "Juno", Scope.RELEASE)
    assert text.body.startswith("Seven years have passed since Burial first stopped us dead")
    assert [(t.name, t.kind) for t in partial.tags] == [("Deep Dubstep", TagKind.GENRE)]
    assert [(link.service, link.url, link.target) for link in partial.links] == [
        ("juno", UNTRUE, LinkTarget.ALBUM),
    ]


@pytest.mark.asyncio
async def test_track_is_found_in_the_tracklist_of_its_release() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query("Burial - Archangel", EntityKind.TRACK))

    assert urls(seen) == [SEARCH, UNTRUE]
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.title, candidate.date) == (
        EntityKind.TRACK,
        "Archangel",
        "2007-11-02",
    )
    assert [(r.kind, r.target.type, r.target.name, r.target.url) for r in partial.relations] == [
        (RelationKind.APPEARS_ON, EntityType.RELEASE, "Untrue", UNTRUE),
    ]


@pytest.mark.asyncio
async def test_the_todd_terry_club_mix_is_the_todd_terry_remix() -> None:
    adapter, seen = make()
    query = parse_query("Everything but the Girl - Missing (Todd Terry Remix)", EntityKind.TRACK)

    partial = await looked_up(adapter, query)
    dossier = merge(query, [partial], generated_at=NOW)

    assert urls(seen) == [SEARCH, MISSING_BLACK]
    assert partial.candidate is not None
    assert partial.candidate.title == "Missing (Todd Terry club mix)"
    assert dossier.identity.version.kind is VersionKind.REMIX
    assert [r.kind for r in dossier.relations] == [RelationKind.APPEARS_ON]
    assert [(t.name, t.kind) for t in dossier.tags] == [
        ("Disco/Nu-Disco", TagKind.GENRE),
        ("Balearic House", TagKind.TAG),
        ("90s House", TagKind.TAG),
        ("Garage House", TagKind.TAG),
    ]


@pytest.mark.asyncio
async def test_the_original_is_found_on_the_album() -> None:
    adapter, seen = make()

    partial = await looked_up(
        adapter,
        parse_query("Everything but the Girl - Missing", EntityKind.TRACK),
    )

    assert urls(seen) == [SEARCH, AMPLIFIED_HEART]
    assert partial.candidate is not None
    assert partial.candidate.title == "Missing"
    assert partial.relations[0].target.name == (
        "Amplified Heart (25th Anniversary Edition) (half-speed remastered)"
    )


@pytest.mark.asyncio
async def test_unknown_label_and_missing_date_are_left_out() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query(f"{MISSING_COLOURED}?ref=search"))

    assert urls(seen) == [MISSING_COLOURED]
    assert partial.candidate is not None
    assert (partial.candidate.labels, partial.candidate.date) == ([], None)
    assert partial.texts == []


@pytest.mark.asyncio
async def test_page_found_by_earlier_passes() -> None:
    adapter, seen = make()
    query = parse_query("Burial - Untrue", EntityKind.ALBUM)
    link = Link(service="juno", url=UNTRUE, target=LinkTarget.ALBUM, sources=[])

    await looked_up(adapter, query, LookupContext(query=query, links=[link]))

    assert urls(seen) == [UNTRUE]


@pytest.mark.asyncio
async def test_page_without_canonical_link_keeps_the_requested_url() -> None:
    page = (
        '<div id="product-page-music"><h2 itemprop="byArtist">BURIAL</h2>'
        '<div class="product-title"><span itemprop="name">Untrue</span></div>'
        '<div class="product-meta"><div class="mb-1">Released: soon</div>'
        '<div class="mb-1">Genre: Dubstep</div><div class="mb-1">Note</div></div></div>'
    )
    adapter, _ = make(pages={UNTRUE: page})

    partial = await looked_up(adapter, parse_query(f"{UNTRUE}?ref=x"))

    assert partial.candidate is not None
    assert (partial.candidate.url, partial.candidate.date) == (UNTRUE, None)
    assert [t.name for t in partial.tags] == ["Dubstep"]


@pytest.mark.asyncio
async def test_track_missing_from_the_release_page() -> None:
    listing = results(("BURIAL", "Untrue", "/products/burial-untrue-vinyl/285827-01/", ["Kindred"]))
    adapter, _ = make(pages={SEARCH: listing})

    with pytest.raises(NotFoundError, match="does not list the track"):
        await looked_up(adapter, parse_query("Burial - Kindred", EntityKind.TRACK))


@pytest.mark.asyncio
async def test_no_matching_result() -> None:
    listing = results(("", "Untrue", "/products/x/1-01/", []), ("OTHER", "Untrue", "/p/2-01/", []))
    adapter, _ = make(pages={SEARCH: listing})

    with pytest.raises(NotFoundError, match="no matching juno"):
        await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.ALBUM))


@pytest.mark.asyncio
async def test_challenge_is_blocked() -> None:
    adapter, _ = make(status=403)

    with pytest.raises(BlockedError):
        await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.ALBUM))


@pytest.mark.asyncio
async def test_unreadable_page() -> None:
    adapter, _ = make(pages={UNTRUE: "<html><body>Gone</body></html>"})

    with pytest.raises(SourceError, match="names no release"):
        await looked_up(adapter, parse_query(UNTRUE))


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ('"Missing" (Todd Terry club mix)', ("EBTG", "Missing (Todd Terry club mix)")),
        ('"Archangel"', ("EBTG", "Archangel")),
        ('KODE9 - "Cell 3"', ("KODE9", "Cell 3")),
        ("Untitled", ("EBTG", "Untitled")),
    ],
)
def test_tracklist_entries(entry: str, expected: tuple[str, str]) -> None:
    assert p.track_entry(entry, "EBTG") == expected
