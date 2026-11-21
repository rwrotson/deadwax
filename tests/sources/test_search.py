from collections.abc import Callable, Mapping

import httpx
import pytest

from deadwax.core import (
    ArtistIdentity,
    EntityKind,
    ExternalId,
    IdKind,
    LabelIdentity,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RecordCandidate,
    RecordIdentity,
    RecordKey,
    Sourced,
    SourceGroup,
    VersionInfo,
    VersionKind,
)
from deadwax.sources import LookupConfig, SourceSettings, parse_query
from deadwax.sources._http import HttpResources
from deadwax.sources._search import SearchHit, SearchPageAdapter, name_key, pick_hit, search_key

SOURCES = [Provenance(source="musicbrainz")]


SEARCH = "https://shop.example/search"
TRACK = parse_query("Burial - Archangel", EntityKind.TRACK)


class FakeShop(SearchPageAdapter):
    """Search results are lines of 'artist|title|url'; a page holds 'artist|title'."""

    name = "fakeshop"
    group = SourceGroup.SHOPS
    pass_ = Pass.ENRICH
    capabilities = frozenset()
    service = "bandcamp"

    @property
    def settings(self) -> SourceSettings:
        return SourceSettings()

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        return SEARCH, {"q": f"{key.artist} {key.title}"}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:
        hits = []
        for line in content.decode().splitlines():
            artist, title, page = line.split("|")
            hits.append(SearchHit(page, RecordKey(artist, title, EntityKind.TRACK)))
        return hits

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        artist, title = content.decode().split("|")
        candidate = RecordCandidate(kind=EntityKind.TRACK, artist=artist, title=title, url=url)
        return Partial(source=self.name, candidate=candidate)


def shop(config: LookupConfig, pages: dict[str, str], requested: list[str]) -> FakeShop:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        page = pages.get(url.split("?", maxsplit=1)[0])
        return httpx.Response(200, text=page) if page is not None else httpx.Response(404)

    return FakeShop(config, HttpResources(transport=httpx.MockTransport(handler)))


async def looked_up(
    adapter: FakeShop,
    query: Query = TRACK,
    context: LookupContext | None = None,
) -> Partial:
    try:
        return await adapter.lookup(query, context or LookupContext(query=query))
    finally:
        await adapter.aclose()


def hit(title: str, url: str) -> SearchHit:
    return SearchHit(url, RecordKey("Everything but the Girl", title, EntityKind.TRACK))


def test_search_key_prefers_the_query_text() -> None:
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)

    key = search_key(query, LookupContext(query=query))

    assert key is not None
    assert (key.artist, key.title, key.kind) == ("Radiohead", "Paranoid Android", EntityKind.TRACK)


def test_search_key_of_a_url_query_comes_from_earlier_passes() -> None:
    query = parse_query("https://example.org/record")
    remix = VersionInfo(kind=VersionKind.REMIX, detail="Todd Terry remix")
    identity = RecordIdentity(
        kind=EntityKind.TRACK,
        artist=Sourced(value="Everything but the Girl", sources=SOURCES),
        title=Sourced(value="Missing (Todd Terry remix)", sources=SOURCES),
        version=remix,
    )

    key = search_key(query, LookupContext(query=query, identity=identity))

    assert search_key(query, LookupContext(query=query)) is None
    assert key is not None
    assert (key.kind, key.version) == (EntityKind.TRACK, remix)


@pytest.mark.asyncio
async def test_search_page_adapter_searches_picks_and_reads_the_page(
    config: LookupConfig,
) -> None:
    requested: list[str] = []
    pages = {
        SEARCH: "Burial|Ghost Hardware|/ghost\nBurial|Archangel|/archangel",
        "https://shop.example/archangel": "Burial|Archangel",
    }

    partial = await looked_up(shop(config, pages, requested))

    assert isinstance(partial.candidate, RecordCandidate)
    assert partial.candidate.title == "Archangel"
    assert partial.candidate.url == "https://shop.example/archangel"
    assert requested == [f"{SEARCH}?q=Burial+Archangel", "https://shop.example/archangel"]


@pytest.mark.asyncio
async def test_search_page_adapter_reads_a_resolved_url_without_searching(
    config: LookupConfig,
) -> None:
    requested: list[str] = []
    url = "https://burial.bandcamp.com/track/archangel"
    adapter = shop(config, {url: "Burial|Archangel"}, requested)
    query = parse_query(url)

    partial = await looked_up(adapter, query)

    assert adapter.resolves(query)
    assert not adapter.resolves(TRACK)
    assert partial.candidate is not None
    assert requested == [url]


@pytest.mark.asyncio
async def test_search_page_adapter_reads_a_page_found_by_earlier_passes(
    config: LookupConfig,
) -> None:
    requested: list[str] = []
    url = "https://burial.bandcamp.com/track/archangel"
    link = Link(service="bandcamp", target=LinkTarget.TRACK, url=url, sources=SOURCES)

    await looked_up(
        shop(config, {url: "Burial|Archangel"}, requested),
        context=LookupContext(query=TRACK, links=[link]),
    )

    assert requested == [url]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "results", "message"),
    [
        (parse_query("https://shop.example/record"), "", "neither the query nor"),
        (TRACK, "Burial|Untrue|/untrue\nKode9|Archangel|/kode9", "no matching fakeshop"),
    ],
)
async def test_search_page_adapter_not_found(
    config: LookupConfig,
    query: Query,
    results: str,
    message: str,
) -> None:
    adapter = shop(config, {SEARCH: results}, [])

    with pytest.raises(NotFoundError, match=message):
        await looked_up(adapter, query)


def test_pick_hit_prefers_the_record_and_falls_back_to_another_version() -> None:
    reference = RecordKey("Everything but the Girl", "Missing", EntityKind.TRACK)
    unrelated = hit("Driving", "/driving")
    remix = hit("Missing (Todd Terry Remix)", "/remix")
    original = hit("Missing", "/missing")

    assert pick_hit(reference, [unrelated, remix, original]) == original
    assert pick_hit(reference, [unrelated, remix]) == remix
    assert pick_hit(reference, [unrelated]) is None


def test_pick_hit_traces_the_hits_it_compared(
    traced: Callable[[str], list[dict[str, object]]],
) -> None:
    reference = RecordKey("Everything but the Girl", "Missing", EntityKind.TRACK)

    pick_hit(reference, [hit("Driving", "/driving"), hit("Missing", "/missing"), hit("X", "/x")])

    [event] = traced("search.pick")
    assert event["picked"] == "/missing"
    assert event["compared"] == 2
    assert [(h["url"], h["verdict"]) for h in event["hits"]] == [  # type: ignore[attr-defined]
        ("/driving", "no_match"),
        ("/missing", "match"),
    ]


def test_name_key_takes_the_query_name() -> None:
    query = parse_query("Burial", EntityKind.ARTIST)

    key = name_key(query, LookupContext(query=query))

    assert key is not None
    assert (key.name, key.kind, dict(key.ids)) == ("Burial", EntityKind.ARTIST, {})


def test_name_key_of_a_url_takes_the_name_and_ids_found_earlier() -> None:
    query = parse_query("https://www.discogs.com/artist/166535")
    identity = ArtistIdentity(
        name=Sourced(value="Burial", sources=SOURCES),
        external_ids=[
            ExternalId(kind=IdKind.MUSICBRAINZ_ARTIST, value="a", sources=SOURCES),
            ExternalId(kind=IdKind.MUSICBRAINZ_ARTIST, value="b", sources=SOURCES),
        ],
    )

    key = name_key(query, LookupContext(query=query, identity=identity))

    assert key is not None
    assert key.name == "Burial"
    assert dict(key.ids) == {IdKind.MUSICBRAINZ_ARTIST: "a", IdKind.DISCOGS_ARTIST: "166535"}


def test_name_key_ignores_an_identity_of_another_kind() -> None:
    query = parse_query("https://www.discogs.com/artist/166535")
    identity = LabelIdentity(name=Sourced(value="Hyperdub", sources=SOURCES))

    assert name_key(query, LookupContext(query=query, identity=identity)) is None


def test_name_key_of_a_record_query_is_none() -> None:
    assert name_key(TRACK, LookupContext(query=TRACK)) is None
