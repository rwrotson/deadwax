import html
import json
from collections.abc import Mapping

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
    Provenance,
    Query,
    RelationKind,
    SourceError,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.bandcamp import BandcampAdapter
from deadwax.sources.bandcamp.adapter import MOBILE_API, SEARCH_API, SEARCH_PAGE

ALBUM = "https://band.bandcamp.com/album/record"
TRACK = "https://band.bandcamp.com/track/song"
CHALLENGE = b"<html><title>Client Challenge</title><script src='/_fs-ch-x/a.js'></script></html>"

type Route = tuple[int, bytes]


def page(
    item_type: str,
    item_id: int,
    title: str,
    *,
    tracks: list[dict[str, object]] | None = None,
    album_url: str | None = None,
) -> bytes:
    tralbum = {
        "id": item_id,
        "item_type": item_type,
        "artist": "Band",
        "url": ALBUM if item_type == "album" else TRACK,
        "album_url": album_url,
        "current": {"title": title, "band_id": 7, "release_date": "01 Jan 2020 00:00:00 GMT"},
        "trackinfo": tracks or [],
    }
    ld: dict[str, object] = {
        "@type": "MusicAlbum" if item_type == "album" else "MusicRecording",
        "name": title,
        "keywords": ["drone"],
        "publisher": {"@id": "https://band.bandcamp.com", "name": "Band"},
    }
    if album_url:
        ld["inAlbum"] = {"name": "Record", "byArtist": {"name": "Band"}}
    return (
        f'<div data-tralbum="{html.escape(json.dumps(tralbum))}"></div>'
        f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    ).encode()


def details(item_id: int, item_type: str, label: str | None = None) -> bytes:
    tags = [{"name": "drone"}, {"name": "Town", "isloc": True}]
    body = {"id": item_id, "type": item_type, "title": "Record", "label": label,
            "band": {"band_id": 7, "name": "Band"}, "tralbum_artist": "Band",
            "bandcamp_url": ALBUM, "tags": tags}  # fmt: skip
    return json.dumps(body).encode()


ALBUM_PAGE = page(
    "album",
    1,
    "Record",
    tracks=[{"id": 2, "title": "Song", "title_link": "/track/song"}],
)
TRACK_PAGE = page("track", 2, "Song", album_url="/album/record")


def adapter(routes: Mapping[str, Route], seen: list[str] | None = None) -> BandcampAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url.copy_with(query=None))
        if seen is not None:
            seen.append(f"{request.method} {url}")
        status, body = routes.get(url, (404, b"missing"))
        return httpx.Response(status, content=body)

    config = SourcesConfig.model_validate(
        {"bandcamp": {"rate": 1000}, "http": {"retries": 0, "escalation": []}},
    )
    return BandcampAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


def search(*results: dict[str, object]) -> Route:
    return 200, json.dumps({"auto": {"results": list(results)}}).encode()


def result(item_type: str, item_id: int, name: str, url: str) -> dict[str, object]:
    return {"type": item_type, "id": item_id, "name": name, "band_id": 7, "band_name": "Band",
            "item_url_path": url}  # fmt: skip


def context(query: Query, *bandcamp: str) -> LookupContext:
    links = [
        Link(
            service="bandcamp",
            url=url,
            target=LinkTarget.ALBUM,
            sources=[Provenance(source="mb")],
        )
        for url in bandcamp
    ]
    return LookupContext(query=query, links=links)


@pytest.mark.asyncio
async def test_query_url_is_read_with_the_mobile_api() -> None:
    query = parse_query(ALBUM)
    found = adapter({ALBUM: (200, ALBUM_PAGE), MOBILE_API: (200, details(1, "a", "Label"))})

    partial = await found.lookup(query, LookupContext(query=query))

    assert found.resolves(query)
    assert partial.candidate is not None
    assert partial.candidate.ids == {IdKind.BANDCAMP_ALBUM: "1"}
    assert [label.name for label in partial.candidate.labels] == ["Label"]
    assert [tag.name for tag in partial.tags] == ["drone"]


@pytest.mark.asyncio
async def test_track_query_follows_the_track_page_of_an_album_link() -> None:
    query = parse_query("Band - Song", EntityKind.TRACK)
    seen: list[str] = []
    found = adapter({ALBUM: (200, ALBUM_PAGE), TRACK: (200, TRACK_PAGE)}, seen)

    partial = await found.lookup(query, context(query, ALBUM))

    assert partial.candidate is not None
    assert partial.candidate.kind is EntityKind.TRACK
    assert f"GET {TRACK}" in seen
    assert RelationKind.APPEARS_ON in {r.kind for r in partial.relations}


@pytest.mark.asyncio
async def test_track_missing_from_the_album() -> None:
    query = parse_query("Band - Other", EntityKind.TRACK)
    found = adapter({ALBUM: (200, ALBUM_PAGE)})

    with pytest.raises(NotFoundError, match="not on the Bandcamp album"):
        await found.lookup(query, context(query, ALBUM))


@pytest.mark.asyncio
async def test_album_query_moves_from_a_track_page_to_its_album() -> None:
    query = parse_query("Band - Record", EntityKind.ALBUM)
    found = adapter({TRACK: (200, TRACK_PAGE), ALBUM: (200, ALBUM_PAGE)})

    partial = await found.lookup(query, context(query, TRACK))

    assert partial.candidate is not None
    assert partial.candidate.kind is EntityKind.ALBUM


@pytest.mark.asyncio
async def test_track_page_without_album() -> None:
    query = parse_query("Band - Record", EntityKind.ALBUM)
    found = adapter({TRACK: (200, page("track", 2, "Song"))})

    with pytest.raises(NotFoundError, match="names no album"):
        await found.lookup(query, context(query, TRACK))


@pytest.mark.asyncio
async def test_page_without_release_data() -> None:
    query = parse_query(ALBUM)

    with pytest.raises(SourceError, match="no release data"):
        await adapter({ALBUM: (200, b"<html></html>")}).lookup(query, LookupContext(query=query))


@pytest.mark.asyncio
async def test_nothing_to_search_for() -> None:
    query = Query(url="https://example.com/x")

    with pytest.raises(NotFoundError, match="neither the query"):
        await adapter({}).lookup(query, LookupContext(query=query))


@pytest.mark.asyncio
async def test_search_without_a_match() -> None:
    query = parse_query("Band - Record", EntityKind.ALBUM)
    seen: list[str] = []
    found = adapter({SEARCH_API: search(result("a", 9, "Else", ALBUM))}, seen)

    with pytest.raises(NotFoundError, match="no matching"):
        await found.lookup(query, LookupContext(query=query))
    assert f"GET {SEARCH_PAGE}" not in seen


@pytest.mark.asyncio
async def test_html_search_when_the_endpoint_fails() -> None:
    query = parse_query("Band - Record", EntityKind.ALBUM)
    search_page = (
        '<li class="searchresult"><div class="itemtype">ALBUM</div>'
        f'<div class="heading"><a href="{ALBUM}">Record</a></div>'
        '<div class="subhead">by Band</div></li>'
    ).encode()
    found = adapter(
        {SEARCH_API: (500, b"error"), SEARCH_PAGE: (200, search_page), ALBUM: (200, ALBUM_PAGE)},
    )

    partial = await found.lookup(query, LookupContext(query=query))

    assert partial.candidate is not None
    assert partial.candidate.title == "Record"


@pytest.mark.asyncio
async def test_direct_page_when_both_search_routes_return_503() -> None:
    query = parse_query("Band - Record", EntityKind.ALBUM)
    seen: list[str] = []
    found = adapter(
        {
            SEARCH_API: (503, b"temporary failure"),
            SEARCH_PAGE: (503, b"temporary failure"),
            ALBUM: (200, ALBUM_PAGE),
        },
        seen,
    )

    partial = await found.lookup(query, context(query))

    assert partial.candidate is not None
    assert partial.candidate.url == ALBUM
    assert f"GET {ALBUM}" in seen


@pytest.mark.asyncio
async def test_direct_page_must_match_the_query() -> None:
    query = parse_query("Band - Record", EntityKind.ALBUM)
    found = adapter(
        {
            SEARCH_API: (503, b"temporary failure"),
            SEARCH_PAGE: (503, b"temporary failure"),
            ALBUM: (200, page("album", 1, "Other")),
        },
    )

    with pytest.raises(SourceError, match="HTTP 503"):
        await found.lookup(query, context(query))


@pytest.mark.asyncio
async def test_blocked_page_falls_back_to_the_mobile_api() -> None:
    query = parse_query("Band - Record", EntityKind.ALBUM)
    found = adapter(
        {
            SEARCH_API: search(result("a", 1, "Record", ALBUM)),
            ALBUM: (200, CHALLENGE),
            MOBILE_API: (200, details(1, "a")),
        },
    )

    partial = await found.lookup(query, LookupContext(query=query))

    assert partial.candidate is not None
    assert partial.candidate.url == ALBUM
    assert [tag.name for tag in partial.tags] == ["drone"]


@pytest.mark.asyncio
async def test_blocked_page_and_mobile_api() -> None:
    query = parse_query("Band - Record", EntityKind.ALBUM)
    found = adapter({SEARCH_API: search(result("a", 1, "Record", ALBUM)), ALBUM: (200, CHALLENGE)})

    with pytest.raises(BlockedError):
        await found.lookup(query, LookupContext(query=query))


@pytest.mark.asyncio
async def test_blocked_page_without_band_id() -> None:
    query = parse_query("Band - Record", EntityKind.ALBUM)
    hit = result("a", 1, "Record", ALBUM) | {"band_id": None}
    found = adapter({SEARCH_API: search(hit), ALBUM: (200, CHALLENGE)})

    with pytest.raises(BlockedError):
        await found.lookup(query, LookupContext(query=query))


@pytest.mark.asyncio
async def test_label_account_lists_label_releases() -> None:
    query = parse_query(ALBUM)
    grid = (
        b'<li class="music-grid-item" data-item-id="album-5"><a href="/album/other">'
        b'<p class="title">Other</p></a></li>'
    )
    found = adapter(
        {
            ALBUM: (200, ALBUM_PAGE),
            MOBILE_API: (200, details(1, "a", "Band")),
            "https://band.bandcamp.com/music": (200, grid),
        },
    )

    partial = await found.lookup(query, LookupContext(query=query))

    releases = [r for r in partial.relations if r.kind is RelationKind.LABEL_RELEASE]
    assert [r.target.name for r in releases] == ["Other"]


@pytest.mark.asyncio
async def test_label_page_failure_costs_only_the_label_releases() -> None:
    query = parse_query(ALBUM)
    found = adapter({ALBUM: (200, ALBUM_PAGE), MOBILE_API: (200, details(1, "a", "Band"))})

    partial = await found.lookup(query, LookupContext(query=query))

    assert RelationKind.LABEL_RELEASE not in {r.kind for r in partial.relations}
    assert partial.candidate is not None
