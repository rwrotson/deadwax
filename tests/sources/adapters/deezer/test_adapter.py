import json

import httpx
import pytest

from deadwax.core import (
    EntityKind,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Query,
    SourceError,
)
from deadwax.sources import SourcesConfig, parse_query
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.deezer import DeezerAdapter

ALBUM_URL = "https://www.deezer.com/album/14880539"
TRACK_URL = "https://www.deezer.com/track/138539973"


def page(data: dict[str, object]) -> bytes:
    return f"<script>window.__DZR_APP_STATE__ = {json.dumps({'DATA': data})};</script>".encode()


def adapter(routes: dict[str, tuple[int, bytes]], seen: list[str] | None = None) -> DeezerAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        status, body = routes.get(str(request.url), (404, b"missing"))
        return httpx.Response(status, content=body)

    config = SourcesConfig.model_validate(
        {"deezer": {"rate": 1000}, "http": {"retries": 0, "escalation": []}},
    )
    return DeezerAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


def context(query: Query) -> LookupContext:
    return LookupContext(query=query)


def album_page(title: str = "OK Computer") -> bytes:
    return page(
        {
            "ALB_TITLE": title,
            "ART_NAME": "Radiohead",
            "ART_ID": "399",
            "UPC": "634904078164",
            "LABEL_NAME": "XL Recordings",
            "DIGITAL_RELEASE_DATE": "1997-05-21",
            "GENRES": {"data": [{"name": "Rock"}]},
        },
    )


def track_page(title: str = "Paranoid Android") -> bytes:
    return page(
        {
            "SNG_TITLE": title,
            "ART_NAME": "Radiohead",
            "ART_ID": "399",
            "ALB_ID": "14880539",
            "ALB_TITLE": "OK Computer",
            "ISRC": "GBAYE9701376",
        },
    )


@pytest.mark.asyncio
async def test_album_url_reads_html_identity_and_tags() -> None:
    query = parse_query(ALBUM_URL)
    seen: list[str] = []

    partial = await adapter({ALBUM_URL: (200, album_page())}, seen).lookup(query, context(query))

    assert partial.candidate is not None
    assert partial.candidate.title == "OK Computer"
    assert partial.candidate.upcs == ["634904078164"]
    assert [tag.name for tag in partial.tags] == ["Rock"]
    assert seen == [ALBUM_URL]


@pytest.mark.asyncio
async def test_track_url_reads_html_identity_and_links() -> None:
    query = parse_query(TRACK_URL)

    partial = await adapter({TRACK_URL: (200, track_page())}).lookup(query, context(query))

    assert partial.candidate is not None
    assert partial.candidate.isrcs == ["GBAYE9701376"]
    assert {link.url for link in partial.links} == {
        TRACK_URL,
        ALBUM_URL,
        "https://www.deezer.com/artist/399",
    }


@pytest.mark.asyncio
async def test_known_link_of_another_kind_does_not_replace_search() -> None:
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)
    search_url = "https://www.deezer.com/search/Radiohead%20Paranoid%20Android/track"
    lookup_context = LookupContext(
        query=query,
        links=[Link(service="deezer", url=ALBUM_URL, target=LinkTarget.ALBUM, sources=[])],
    )
    seen: list[str] = []

    partial = await adapter(
        {
            search_url: (200, f'<a href="{TRACK_URL}">Track</a>'.encode()),
            TRACK_URL: (200, track_page()),
        },
        seen,
    ).lookup(query, lookup_context)

    assert partial.candidate is not None
    assert partial.candidate.url == TRACK_URL
    assert ALBUM_URL not in seen


@pytest.mark.asyncio
async def test_search_skips_other_versions() -> None:
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)
    search_url = "https://www.deezer.com/search/Radiohead%20Paranoid%20Android/track"
    live_url = "https://www.deezer.com/track/1"
    links = f'<a href="{live_url}">Live</a><a href="{TRACK_URL}">Original</a>'.encode()
    seen: list[str] = []
    routes = {
        search_url: (200, links),
        live_url: (200, track_page("Paranoid Android (Live)")),
        TRACK_URL: (200, track_page()),
    }

    partial = await adapter(routes, seen).lookup(query, context(query))

    assert partial.candidate is not None
    assert partial.candidate.url == TRACK_URL
    assert seen == [search_url, live_url, TRACK_URL]


@pytest.mark.asyncio
async def test_search_without_candidates_is_not_found() -> None:
    query = parse_query("Radiohead - OK Computer", EntityKind.ALBUM)
    search_url = "https://www.deezer.com/search/Radiohead%20OK%20Computer/album"

    with pytest.raises(NotFoundError, match="no matching Deezer album"):
        await adapter({search_url: (200, b"<html></html>")}).lookup(query, context(query))


@pytest.mark.asyncio
async def test_missing_record_data_is_an_error() -> None:
    query = parse_query(TRACK_URL)

    with pytest.raises(SourceError, match="no record data"):
        await adapter({TRACK_URL: (200, b"<html></html>")}).lookup(query, context(query))
