import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote

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
from deadwax.sources.phonica import PhonicaAdapter
from deadwax.sources.phonica import parse as p

# Product pages saved from Firefox on 2026-11-13 and trimmed by scripts/saved_pages.py;
# search API answers taken from a HAR recording of the site's own search the same day.
PAGES = Path(__file__).resolve().parent.parent / "fixtures" / "phonica" / "pages"

SITE = "https://www.phonicarecords.com"
SEARCH = f"{SITE}/api/product/json_category_search/"
TRUANT = f"{SITE}/product/burial-truant-rough-sleeper-hyperdub/111124"
TRUANT_CD = f"{SITE}/product/burial-truant-rough-sleeper-cd-hyperdub/111125"
COLONIAL_SAVED = f"{SITE}/product/huercos-colonial-patterns-lp-software/116278"
COLONIAL = f"{SITE}/product/huerco-s-colonial-patterns-lp-software/116278"
SERVED = {TRUANT: "product_111124", COLONIAL_SAVED: "product_116278"}

# Search terms answered with a saved API answer; other terms find nothing.
SEARCHES = {"Truant": "search_truant.json"}
NOW = datetime(2026, 11, 13, tzinfo=UTC)

SUCURI = "<html><script>var sucuri_cloudproxy_js='';</script></html>"


def api(*items: tuple[str, str, str, list[str]]) -> str:
    products = {
        str(n): {
            "artist": artist,
            "album": title,
            "slug": slug,
            "product_playlist": [{"trackname": track} for track in tracks],
        }
        for n, (artist, title, slug, tracks) in enumerate(items)
    }
    return json.dumps({**products, "1x": {"album": "skipped"}, "9": {"album": "invalid"}})


def make(
    pages: dict[str, str] | None = None,
    status: int = 200,
) -> tuple[PhonicaAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, text=SUCURI, headers={"server": "Sucuri/Cloudproxy"})
        url = str(request.url).split("?", maxsplit=1)[0]
        if pages is not None and url in pages:
            return httpx.Response(200, text=pages[url])
        if url.startswith(SEARCH):
            term = unquote(url.removeprefix(SEARCH).removesuffix("/0"))
            assert request.method == "POST"
            assert parse_qs(request.content.decode()) == {
                "id": ["0"],
                "href": [f"/search/{term}/"],
                "offset": ["0"],
            }
            answer = PAGES / SEARCHES.get(term, "search_not_found.json")
            return httpx.Response(200, content=answer.read_bytes())
        if (name := SERVED.get(url)) is None:
            return httpx.Response(404)
        return httpx.Response(200, content=(PAGES / f"{name}.html").read_bytes())

    config = SourcesConfig.model_validate(
        {
            "phonica": {"rate": 1000, "html_transports": ["httpx"]},
            "http": {"retries": 0, "escalation": []},
        },
    )
    return PhonicaAdapter(config, HttpResources(transport=httpx.MockTransport(handler))), seen


async def looked_up(
    adapter: PhonicaAdapter,
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
async def test_release_page_with_text_genres_label_and_also_bought() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query(TRUANT))

    assert urls(seen) == [TRUANT]
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.artist, candidate.title, candidate.date, candidate.url) == (
        EntityKind.ALBUM,
        "BURIAL",
        "Truant / Rough Sleeper",
        None,
        TRUANT,
    )
    assert [(label.name, label.catalog_number) for label in candidate.labels] == [
        ("HYPERDUB", None),
    ]
    [text] = partial.texts
    assert (text.kind, text.publication, text.scope) == (TextKind.SHOP, "Phonica", Scope.RELEASE)
    assert text.body == (
        "Burial's latest 12\" for Hyperdub, a true epic clocking in with a total of over "
        "25minutes of music, absolutely superlative stuff!"
    )
    assert [(t.name, t.kind) for t in partial.tags] == [
        ("Electronica / Ambient", TagKind.GENRE),
        ("Bass / Breaks / Dubstep", TagKind.GENRE),
        ("Experimental / Avant-Garde / Leftfield / Drone", TagKind.GENRE),
    ]
    assert [(r.kind, r.target.type, r.target.artist, r.target.name) for r in partial.relations] == [
        (RelationKind.SIMILAR, EntityType.RELEASE, "SOUND STREAM", "Julie's Theme [2026 Repress)"),
        (RelationKind.SIMILAR, EntityType.RELEASE, "D'ANGELO", "Voodoo"),
        (RelationKind.SIMILAR, EntityType.RELEASE, "THE NIGHTWRITERS", "Let the Music (Use You)"),
    ]
    assert (
        partial.relations[1].target.url == f"{SITE}/product/dangelo-voodoo-lp-back-to-black/111235"
    )
    assert [(link.service, link.url, link.target) for link in partial.links] == [
        ("phonica", TRUANT, LinkTarget.ALBUM),
    ]


@pytest.mark.asyncio
async def test_release_search_takes_the_first_edition_listed() -> None:
    page = (
        '<div id="page-single"><a class="single-artist">BURIAL</a>'
        '<a class="single-title">Truant / Rough Sleeper CD</a></div>'
    )
    adapter, seen = make(pages={TRUANT_CD: page})

    partial = await looked_up(
        adapter,
        parse_query("Burial - Truant / Rough Sleeper", EntityKind.ALBUM),
    )

    assert urls(seen) == [f"{SEARCH}Truant/0", TRUANT_CD]
    assert partial.candidate is not None
    assert partial.candidate.title == "Truant / Rough Sleeper"


@pytest.mark.asyncio
async def test_track_is_found_by_artist_on_the_release_that_lists_it() -> None:
    burial = api(
        ("BURIAL", "Antidawn CD", "product/burial-antidawn-cd-hyperdub/177938", ["Antidawn"]),
        (
            "BURIAL",
            "Truant / Rough Sleeper",
            "/product/burial-truant-rough-sleeper-hyperdub/111124",
            ["Truant ", "Rough Sleeper"],
        ),
    )
    adapter, seen = make(pages={f"{SEARCH}Burial/0": burial})

    partial = await looked_up(adapter, parse_query("Burial - Rough Sleeper", EntityKind.TRACK))

    assert urls(seen) == [f"{SEARCH}Rough%20Sleeper/0", f"{SEARCH}Burial/0", TRUANT]
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.artist, candidate.title) == (
        EntityKind.TRACK,
        "BURIAL",
        "Rough Sleeper",
    )
    assert [(r.kind, r.target.name, r.target.url) for r in partial.relations[:1]] == [
        (RelationKind.APPEARS_ON, "Truant / Rough Sleeper", TRUANT),
    ]
    assert [r.kind for r in partial.relations[1:]] == [RelationKind.SIMILAR] * 3


@pytest.mark.asyncio
async def test_another_version_is_kept_out_of_the_record() -> None:
    remixes = f"{SITE}/product/burial-truant-remixes/1"
    page = (
        '<div id="page-single"><a class="single-artist">BURIAL</a>'
        '<a class="single-title">Truant Remixes</a>'
        '<div class="single-description">Dubbed out</div>'
        '<table id="playlist"><tr><td class="trackname">Truant (Kode9 Remix)</td></tr></table>'
        "</div>"
    )
    listing = api(
        ("BURIAL", "Truant Remixes", "product/burial-truant-remixes/1", ["Truant (Kode9 Remix)"]),
    )
    adapter, seen = make(pages={f"{SEARCH}Truant/0": listing, remixes: page})
    query = parse_query("Burial - Truant", EntityKind.TRACK)

    partial = await looked_up(adapter, query)
    dossier = merge(query, [partial], generated_at=NOW)

    assert urls(seen)[1:] == [remixes]
    assert dossier.texts == []
    assert [(r.kind, r.target.name) for r in dossier.relations] == [
        (RelationKind.OTHER_VERSION, "Truant (Kode9 Remix)"),
    ]
    assert [d.field for d in dossier.identity.discrepancies] == ["version"]


@pytest.mark.asyncio
async def test_product_url_with_paragraphs_and_a_format_in_the_title() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query(COLONIAL_SAVED))

    assert urls(seen) == [COLONIAL_SAVED]
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.artist, candidate.title, candidate.url) == (
        "HUERCO S.",
        "Colonial Patterns",
        COLONIAL,
    )
    assert [label.name for label in candidate.labels] == ["SOFTWARE"]
    [text] = partial.texts
    paragraphs = text.body.split("\n\n")
    assert len(paragraphs) == 5
    assert paragraphs[0].startswith(
        "Brian Leeds produces electronic music under the name Huerco S.",
    )
    assert paragraphs[1].startswith("Colonial Patterns shares Jon Hassell's")
    assert [t.name for t in partial.tags] == [
        "House / Deep House",
        "Techno / Electro",
        "Electronica / Ambient",
    ]
    assert partial.relations == []


@pytest.mark.asyncio
async def test_page_found_by_earlier_passes() -> None:
    adapter, seen = make()
    query = parse_query("Burial - Truant / Rough Sleeper", EntityKind.ALBUM)
    link = Link(service="phonica", url=TRUANT, target=LinkTarget.ALBUM, sources=[])

    await looked_up(adapter, query, LookupContext(query=query, links=[link]))

    assert urls(seen) == [TRUANT]


@pytest.mark.asyncio
async def test_bare_page_without_canonical_url() -> None:
    page = (
        '<div id="page-single"><a class="single-artist">BURIAL</a>'
        '<a class="single-title">Untrue LP</a><div class="single-description"> </div></div>'
    )
    adapter, _ = make(pages={TRUANT: page})

    partial = await looked_up(adapter, parse_query(f"{TRUANT}?ref=x"))

    assert partial.candidate is not None
    assert (partial.candidate.url, partial.candidate.title, partial.candidate.labels) == (
        TRUANT,
        "Untrue",
        [],
    )
    assert (partial.texts, partial.tags, partial.relations) == ([], [], [])


@pytest.mark.asyncio
async def test_track_missing_from_the_release_page() -> None:
    listing = api(
        ("BURIAL", "Kindred", "product/burial-truant-rough-sleeper-hyperdub/111124", ["Kindred"]),
    )
    adapter, _ = make(pages={f"{SEARCH}Kindred/0": listing})

    with pytest.raises(NotFoundError, match="does not list the track"):
        await looked_up(adapter, parse_query("Burial - Kindred", EntityKind.TRACK))


@pytest.mark.asyncio
async def test_no_matching_result_by_title_or_artist() -> None:
    adapter, seen = make()

    with pytest.raises(NotFoundError, match="no matching phonica"):
        await looked_up(adapter, parse_query("Burial - Untrue (Live)", EntityKind.ALBUM))

    assert urls(seen) == [f"{SEARCH}Untrue/0", f"{SEARCH}Burial/0"]


@pytest.mark.asyncio
async def test_a_self_titled_record_is_searched_once() -> None:
    adapter, seen = make()

    with pytest.raises(NotFoundError):
        await looked_up(adapter, parse_query("Burial - Burial", EntityKind.ALBUM))

    assert urls(seen) == [f"{SEARCH}Burial/0"]


@pytest.mark.asyncio
async def test_search_answer_without_json() -> None:
    adapter, _ = make(pages={f"{SEARCH}Truant/0": "<html>maintenance</html>"})

    with pytest.raises(SourceError, match="without JSON"):
        await looked_up(adapter, parse_query("Burial - Truant", EntityKind.ALBUM))


def test_search_answer_that_is_not_an_object() -> None:
    assert p.search_hits(b"[]", SEARCH) == []


@pytest.mark.asyncio
async def test_sucuri_challenge_is_blocked() -> None:
    adapter, _ = make(status=403)

    with pytest.raises(BlockedError):
        await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.ALBUM))


@pytest.mark.asyncio
async def test_unreadable_page() -> None:
    adapter, _ = make(pages={TRUANT: "<html><body>Gone</body></html>"})

    with pytest.raises(SourceError, match="names no release"):
        await looked_up(adapter, parse_query(TRUANT))


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("Colonial Patterns LP", "Colonial Patterns"),
        ("Antidawn CD", "Antidawn"),
        ("Untrue 2LP", "Untrue"),
        ("Untrue 2 x LP", "Untrue"),
        ("Streetlands EP", "Streetlands EP"),
        ("LP", "LP"),
    ],
)
def test_release_title(printed: str, expected: str) -> None:
    assert p.release_title(printed) == expected


@pytest.mark.parametrize(
    ("title", "term"),
    [
        ("Truant / Rough Sleeper", "Truant"),
        ("Missing (Todd Terry Remix)", "Missing"),
        ("Colonial Patterns", "Colonial Patterns"),
    ],
)
def test_search_term(title: str, term: str) -> None:
    assert p.search_term(title) == term
