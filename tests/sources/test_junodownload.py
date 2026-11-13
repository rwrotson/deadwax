from datetime import UTC, datetime

import httpx
import pytest

from deadwax.core import (
    BlockedError,
    EntityKind,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Query,
    RecordKey,
    RelationKind,
    SourceError,
    TagKind,
    merge,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.junodownload import JunoDownloadAdapter
from deadwax.sources.junodownload import parse as p

SITE = "https://www.junodownload.com"
UNTRUE = f"{SITE}/products/burial-untrue/1234-02/"
SINGLE = f"{SITE}/products/burial-archangel/5678-02/"

SEARCH = """
<div class="jd-listing-item">
  <a class="juno-artist" href="/artists/Burial/">Burial</a>
  <a class="juno-title" href="/products/burial-archangel/5678-02/">Archangel</a>
  <div class="jd-listing-tracklist">
    <span class="juno-track">Archangel (Extended Mix)</span>
  </div>
</div>
<div class="jd-listing-item">
  <a class="juno-artist" href="/artists/Burial/">Burial</a>
  <a class="juno-title" href="/products/burial-untrue/1234-02/">Untrue</a>
  <div class="jd-listing-tracklist">
    <span class="juno-track">Archangel</span>
    <span class="juno-track">Near Dark</span>
  </div>
</div>
<div class="jd-listing-item"><a class="juno-title">No link</a></div>
"""

SINGLE_SEARCH = """
<div class="jd-listing-item">
  <a class="juno-artist">Burial</a>
  <a class="juno-title" href="/products/burial-archangel/5678-02/">Archangel</a>
  <div class="jd-listing-tracklist"><span class="juno-track">Archangel (Extended Mix)</span></div>
</div>
"""

RELEASE = """
<h1 class="product-title">Untrue</h1>
<h2 class="product-artist"><a href="/artists/Burial/">Burial</a></h2>
<div class="product-meta">
  <strong>Label:</strong> <a href="/labels/Hyperdub/">Hyperdub</a><br>
  <strong>Cat:</strong> HDBCD 002<br>
  <strong>Released:</strong> 05 Nov, 2007<br>
  <strong>Genre:</strong> <a href="/dubstep/">Dubstep</a> <a href="/uk-garage/">UK Garage</a><br>
  <strong>Notes:</strong><br>
</div>
<div class="product-tracklist">
  <div class="product-tracklist-track" itemprop="track">
    <span itemprop="name">Untitled</span><div class="col-bpm">&nbsp;</div>
  </div>
  <div class="product-tracklist-track" itemprop="track">
    <span itemprop="name">Archangel</span><div class="col-bpm">139</div>
  </div>
  <div class="product-tracklist-track" itemprop="track">
    <span itemprop="name">Near Dark</span>
    <span itemprop="byArtist">Burial</span><span itemprop="byArtist">Kode9</span>
    <div class="col-bpm">280</div>
  </div>
  <div class="product-tracklist-track" itemprop="track"><div class="col-bpm">140</div></div>
</div>
"""

ARCHANGEL_SINGLE = """
<h1>Archangel</h1>
<div class="product-artist">Burial</div>
<div class="product-tracklist">
  <div class="product-tracklist-track"><span class="juno-title">Archangel (Extended Mix)</span>
  <div class="col-bpm">138.5 BPM</div></div>
</div>
"""

NOW = datetime(2026, 11, 13, tzinfo=UTC)


def make(
    pages: dict[str, str] | None = None,
    status: int = 200,
) -> tuple[JunoDownloadAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    served = {UNTRUE: RELEASE, SINGLE: ARCHANGEL_SINGLE} | (pages or {})

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, headers={"cf-mitigated": "challenge"})
        if request.url.path == "/search/":
            return httpx.Response(200, text=served.get("search", SEARCH))
        found = served.get(str(request.url))
        return httpx.Response(200, text=found) if found is not None else httpx.Response(404)

    config = SourcesConfig.model_validate(
        {"junodownload": {"rate": 1000}, "http": {"retries": 0, "escalation": "none"}},
    )
    adapter = JunoDownloadAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))
    return adapter, seen


async def looked_up(adapter: JunoDownloadAdapter, query: Query) -> Partial:
    try:
        return await adapter.lookup(query, LookupContext(query=query))
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_track_is_read_from_the_release_that_lists_it() -> None:
    adapter, seen = make()
    query = parse_query("Burial - Archangel", EntityKind.TRACK)

    partial = await looked_up(adapter, query)

    assert seen[0].url.params["q[all][]"] == "Burial Archangel"
    assert seen[0].url.params["solrorder"] == "relevancy"
    assert str(seen[1].url) == UNTRUE
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.artist, candidate.title) == (
        EntityKind.TRACK,
        "Burial",
        "Archangel",
    )
    assert (candidate.bpm, candidate.date) == (139, "2007-11-05")
    assert [(label.name, label.catalog_number) for label in candidate.labels] == [
        ("Hyperdub", "HDBCD 002"),
    ]
    assert [(tag.name, tag.kind) for tag in partial.tags] == [
        ("Dubstep", TagKind.GENRE),
        ("UK Garage", TagKind.GENRE),
    ]
    assert [(link.service, link.target) for link in partial.links] == [
        ("junodownload", LinkTarget.ALBUM),
    ]


@pytest.mark.asyncio
async def test_track_artists_and_implausible_tempo() -> None:
    adapter, _ = make()

    partial = await looked_up(adapter, parse_query("Burial - Near Dark", EntityKind.TRACK))

    assert partial.candidate is not None
    assert (partial.candidate.artist, partial.candidate.bpm) == ("Burial & Kode9", None)


@pytest.mark.asyncio
async def test_album() -> None:
    adapter, _ = make()

    partial = await looked_up(adapter, parse_query("Burial - Untrue", EntityKind.ALBUM))

    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.title, candidate.bpm) == (EntityKind.ALBUM, "Untrue", None)


@pytest.mark.asyncio
async def test_release_url_is_read_as_an_album() -> None:
    adapter, seen = make()

    partial = await looked_up(adapter, parse_query(UNTRUE))

    assert [str(request.url) for request in seen] == [UNTRUE]
    assert partial.candidate is not None
    assert partial.candidate.kind is EntityKind.ALBUM


@pytest.mark.asyncio
async def test_another_mix_becomes_a_relation_and_a_discrepancy() -> None:
    adapter, _ = make(pages={"search": SINGLE_SEARCH})
    query = parse_query("Burial - Archangel", EntityKind.TRACK)

    partial = await looked_up(adapter, query)
    dossier = merge(query, [partial], generated_at=NOW)

    assert partial.candidate is not None
    assert partial.candidate.bpm == 138.5
    assert dossier.identity.bpm is None
    assert [relation.kind for relation in dossier.relations] == [RelationKind.OTHER_VERSION]
    assert [d.field for d in dossier.identity.discrepancies] == ["version"]


@pytest.mark.asyncio
async def test_release_that_does_not_list_the_track() -> None:
    adapter, _ = make(pages={"search": SEARCH.replace("Near Dark", "Ghost Hardware")})
    query = parse_query("Burial - Ghost Hardware", EntityKind.TRACK)

    with pytest.raises(NotFoundError, match="does not list the track"):
        await looked_up(adapter, query)


@pytest.mark.asyncio
async def test_no_matching_result() -> None:
    adapter, _ = make(pages={"search": "<html></html>"})

    with pytest.raises(NotFoundError, match="no matching junodownload"):
        await looked_up(adapter, parse_query("Burial - Archangel", EntityKind.TRACK))


@pytest.mark.asyncio
async def test_page_without_a_release() -> None:
    adapter, _ = make(pages={UNTRUE: "<html><h1>Oops</h1></html>"})

    with pytest.raises(SourceError, match="names no release"):
        await looked_up(adapter, parse_query(UNTRUE))


@pytest.mark.asyncio
async def test_refused_page_is_blocked() -> None:
    adapter, _ = make(status=403)

    with pytest.raises(BlockedError):
        await looked_up(adapter, parse_query("Burial - Archangel", EntityKind.TRACK))


def test_search_hits_list_releases_and_their_tracks() -> None:
    hits = p.hits(SEARCH.encode())

    assert [(hit.url, hit.key) for hit in hits][:2] == [
        (
            "/products/burial-archangel/5678-02/",
            RecordKey("Burial", "Archangel", EntityKind.ALBUM),
        ),
        (
            "/products/burial-archangel/5678-02/",
            RecordKey("Burial", "Archangel (Extended Mix)", EntityKind.TRACK),
        ),
    ]
    assert len(hits) == 5


@pytest.mark.parametrize(
    ("text", "date"),
    [("05 Nov, 2007", "2007-11-05"), ("5 November 2007", "2007-11-05"), ("Soon", None)],
)
def test_page_date(text: str, date: str | None) -> None:
    assert p.page_date(text) == date


def test_page_date_with_an_unknown_month() -> None:
    assert p.page_date("05 Foo, 2007") is None
