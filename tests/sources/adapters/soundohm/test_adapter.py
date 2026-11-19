from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from deadwax.core import (
    BlockedError,
    EntityKind,
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
from deadwax.sources.adapters.soundohm import SoundohmAdapter

# Pages fetched on 2026-11-13, trimmed to their JSON-LD and main content.
PAGES = Path(__file__).resolve().parents[3] / "fixtures" / "soundohm" / "pages"

SITE = "https://www.soundohm.com"
SEARCH = f"{SITE}/search"
UNTRUE = f"{SITE}/product/untrue"
SERVED = {SEARCH: "search_burial_untrue.html", UNTRUE: "product_untrue.html"}
NOW = datetime(2026, 11, 13, tzinfo=UTC)


def results(*products: tuple[str, str, str]) -> str:
    items = "".join(
        f'<div class="listing-grid-product product"><div class="product__artists">{artists}</div>'
        f'<a href="{href}" class="product__title">{title}</a></div>'
        for artists, title, href in products
    )
    return f'<div class="listing-grid">{items}</div>'


def product(title: str, facts: str = "", description: str = "") -> str:
    return (
        '<div class="product-page"><div class="product-page__info">'
        f'<h1><a href="/artist/burial">Burial</a></h1><h2>{title}</h2>{facts}</div>'
        f"{description}</div>"
    )


def make(
    pages: dict[str, str] | None = None,
    status: int = 200,
) -> tuple[SoundohmAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, headers={"cf-mitigated": "challenge"})
        url = str(request.url).split("?", maxsplit=1)[0]
        if pages is not None and url in pages:
            return httpx.Response(200, text=pages[url])
        if url in SERVED:
            return httpx.Response(200, content=(PAGES / SERVED[url]).read_bytes())
        return httpx.Response(404)

    config = SourcesConfig.model_validate(
        {"soundohm": {"rate": 1000}, "http": {"retries": 0, "escalation": []}},
    )
    return SoundohmAdapter(config, HttpResources(transport=httpx.MockTransport(handler))), seen


async def looked_up(
    adapter: SoundohmAdapter,
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
async def test_release_by_search_with_full_shop_text() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.ALBUM))

    assert urls(seen) == [SEARCH, UNTRUE]
    assert seen[0].url.params["query"] == "Burial Untrue"
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.artist, candidate.title, candidate.date) == (
        EntityKind.ALBUM,
        "Burial",
        "Untrue",
        "2008",
    )
    assert [(label.name, label.catalog_number) for label in candidate.labels] == [
        ("Hyperdub", "HDB 002CD"),
    ]
    [text] = partial.texts
    assert (text.kind, text.publication, text.scope) == (TextKind.SHOP, "Soundohm", Scope.RELEASE)
    assert text.body.startswith("This is the second full-length release on Hyperdub")
    assert "much-acclaimed Burial. Of all" in text.body
    assert text.body.endswith("some of the beatless pieces have been edited.")
    assert [(t.name, t.kind) for t in partial.tags] == [("Electronic", TagKind.GENRE)]
    assert [(link.service, link.url, link.target) for link in partial.links] == [
        ("soundohm", UNTRUE, LinkTarget.ALBUM),
    ]


@pytest.mark.asyncio
async def test_tracks_are_not_listed() -> None:
    adapter, seen = make()

    with pytest.raises(NotFoundError, match="no matching soundohm"):
        await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.TRACK))

    assert urls(seen) == [SEARCH]


@pytest.mark.asyncio
async def test_another_version_is_kept_out_of_the_record() -> None:
    remixes = f"{SITE}/product/untrue-live"
    pages = {
        SEARCH: results(
            ('<a href="/artist/x">Someone Else</a>', "Untrue", "/product/other"),
            ('<a href="/artist/burial">Burial</a>', "Untrue (Live)", "/product/untrue-live"),
            ("", "No artist", "/product/none"),
        ),
        remixes: product("Untrue (Live)", description="<p>Live.</p>"),
    }
    adapter, seen = make(pages=pages)
    query = parse_query("Burial - Untrue", EntityKind.ALBUM)

    dossier = merge(query, [await looked_up(adapter, query)], generated_at=NOW)

    assert urls(seen) == [SEARCH, remixes]
    assert dossier.texts == []
    assert [(r.kind, r.target.name) for r in dossier.relations] == [
        (RelationKind.OTHER_VERSION, "Untrue (Live)"),
    ]


@pytest.mark.asyncio
async def test_product_url_is_read_without_searching() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query(UNTRUE))

    assert urls(seen) == [UNTRUE]
    assert partial.candidate is not None


@pytest.mark.asyncio
async def test_page_found_by_earlier_passes() -> None:
    adapter, seen = make()
    query = parse_query("Burial - Untrue", EntityKind.ALBUM)
    link = Link(service="soundohm", url=UNTRUE, target=LinkTarget.ALBUM, sources=[])

    await looked_up(adapter, query, LookupContext(query=query, links=[link]))

    assert urls(seen) == [UNTRUE]


@pytest.mark.asyncio
async def test_facts_from_the_page_when_json_ld_is_missing() -> None:
    facts = (
        '<p><span class="product-page__fact"><span class="product-page__fact-key">Genre</span>'
        '<a href="/genre/dub">Dub</a></span><span class="product-page__fact">'
        '<span class="product-page__fact-key">Format</span>LP</span></p>'
        '<div class="product-page__details-fold-item"><b>Year: </b>unknown</div>'
        '<div class="product-page__details-fold-item"><b>Note</b></div>'
    )
    page = product(
        "Untrue",
        facts,
        '<div class="product-page__description">One <em>line</em></div>',
    )
    adapter, _ = make(pages={UNTRUE: page})

    partial = await looked_up(adapter, parse_query(UNTRUE))

    assert partial.candidate is not None
    assert (partial.candidate.date, partial.candidate.labels) == (None, [])
    assert [t.name for t in partial.tags] == ["Dub"]
    assert [t.body for t in partial.texts] == ["One line"]


@pytest.mark.asyncio
async def test_page_without_text_or_genre() -> None:
    adapter, _ = make(
        pages={
            UNTRUE: product("Untrue", description='<div class="product-page__description"> </div>'),
        },
    )

    partial = await looked_up(adapter, parse_query(UNTRUE))

    assert (partial.tags, partial.texts) == ([], [])


@pytest.mark.asyncio
async def test_challenge_is_blocked() -> None:
    adapter, _ = make(status=403)

    with pytest.raises(BlockedError):
        await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.ALBUM))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page",
    ["<html><body>Gone</body></html>", '<div class="product-page"><h2>Untrue</h2></div>'],
)
async def test_unreadable_page(page: str) -> None:
    adapter, _ = make(pages={UNTRUE: page})

    with pytest.raises(SourceError, match="names no release"):
        await looked_up(adapter, parse_query(UNTRUE))
