import json
from urllib.parse import quote

import httpx
import pytest

from deadwax.core import (
    EntityKind,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Pass,
    Provenance,
    SourceError,
    SourceState,
)
from deadwax.sources import LookupConfig, parse_query
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.odesli import OdesliAdapter
from deadwax.sources.adapters.odesli.models import PageData
from deadwax.sources.adapters.odesli.parse import page_data, partial, service_name

SPOTIFY = "https://open.spotify.com/track/6LgJvl0Xdtc73RJ1mmpotq"
AMAZON = "https://music.amazon.com/albums/B01"
TIDAL = "https://listen.tidal.com/track/58990512"

# Page data in the shape song.link rendered on 2026-11-13; unmatched platforms have no URL.
PAGE_DATA = {
    "entityUniqueId": "spotify|song|6LgJvl0Xdtc73RJ1mmpotq",
    "pageUrl": "https://song.link/s/6LgJvl0Xdtc73RJ1mmpotq",
    "entityData": {
        "type": "song",
        "title": "Paranoid Android",
        "artistName": "Radiohead",
        "isrc": "GBAYE9701376",
    },
    "sections": [
        {"sectionId": "section|auto|albumArt", "title": "Paranoid Android"},
        {
            "sectionId": "section|auto|links|listen",
            "links": [
                {"platform": "spotify", "url": SPOTIFY, "show": True},
                {"platform": "appleMusic", "show": True},
                {"platform": "amazonMusic", "url": AMAZON, "show": True},
                {"platform": "tidal", "url": TIDAL, "show": False},
                {"platform": "yandex", "url": "spotify:track:x", "show": True},
            ],
        },
        {
            "sectionId": "section|auto|links|buy",
            "links": [
                {"platform": "itunes", "show": True},
                {"platform": "amazonStore", "url": "https://amazon.com/dp/B01", "show": True},
                {"platform": "spotify", "url": SPOTIFY, "show": True},
            ],
        },
    ],
}  # fmt: skip


def page(data: object) -> bytes:
    payload = json.dumps({"props": {"pageProps": data}, "page": "/[...pages]"})
    script = f'<script id="__NEXT_DATA__" type="application/json">{payload}</script>'
    return f"<html>{script}</html>".encode()


def adapter(requests: list[httpx.Request], body: bytes | None = None) -> OdesliAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=body or page({"pageData": PAGE_DATA}))

    config = LookupConfig.model_validate(
        {"sources": {"odesli": {"rate": 1000}}, "http": {"escalation": []}},
    )
    return OdesliAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_links_on_every_platform_from_a_curated_link() -> None:
    requests: list[httpx.Request] = []
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)
    spotify = Link(
        service="spotify",
        url=SPOTIFY,
        target=LinkTarget.TRACK,
        sources=[Provenance(source="mb")],
    )

    found = await adapter(requests).lookup(query, LookupContext(query=query, links=[spotify]))

    assert str(requests[0].url) == f"https://song.link/{quote(SPOTIFY, safe='')}"
    assert "Mozilla" in requests[0].headers["user-agent"]
    assert found.candidate is not None
    assert (found.candidate.title, found.candidate.isrcs) == ("Paranoid Android", ["GBAYE9701376"])
    assert [(link.service, link.target) for link in found.links] == [
        ("spotify", LinkTarget.TRACK),
        ("amazon_music", LinkTarget.TRACK),
        ("amazon_store", LinkTarget.TRACK),
    ]
    assert found.links[0].sources[0].url == "https://song.link/s/6LgJvl0Xdtc73RJ1mmpotq"


@pytest.mark.asyncio
async def test_query_url_is_the_seed_and_albums_have_album_links() -> None:
    requests: list[httpx.Request] = []
    entity = {"type": "album", "title": "OK Computer", "artistName": "Radiohead",
              "upc": "634904078164"}  # fmt: skip
    album = PAGE_DATA | {"entityData": entity}
    query = parse_query("https://open.spotify.com/album/6dVIqQ8qmQ5GBnJ9shOYGE")

    found = await adapter(requests, page({"pageData": album})).lookup(
        query,
        LookupContext(query=query),
    )

    assert str(requests[0].url).endswith("open.spotify.com%2Falbum%2F6dVIqQ8qmQ5GBnJ9shOYGE")
    assert found.candidate is not None
    assert (found.candidate.kind, found.candidate.upcs) == (EntityKind.ALBUM, ["634904078164"])
    assert {link.target for link in found.links} == {LinkTarget.ALBUM}


@pytest.mark.asyncio
async def test_without_a_streaming_url_there_is_nothing_to_expand() -> None:
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)

    with pytest.raises(NotFoundError):
        await adapter([]).lookup(query, LookupContext(query=query))


def test_unknown_record_redirects_to_a_page_without_data() -> None:
    with pytest.raises(NotFoundError):
        page_data(page({}), "https://song.link/not-found")


@pytest.mark.parametrize(
    "body",
    [b"<html>Just text</html>", page({"pageData": {"sections": "wrong"}})],
)
def test_unexpected_pages(body: bytes) -> None:
    with pytest.raises(SourceError):
        page_data(body, "https://song.link/x")


def test_links_to_another_record_on_the_seed_provider_are_dropped() -> None:
    # song.link's page of Apple track 5027215 linked the instrumental 5027223 (2026-11-13).
    original = "https://geo.music.apple.com/de/album/_/5027229?i=5027215&mt=1&app=music"
    instrumental = "https://geo.music.apple.com/de/album/_/5027229?i=5027223&mt=1&app=music"
    deezer = "https://www.deezer.com/track/67629072"
    data = PageData.model_validate(
        {
            "entityUniqueId": "itunes|song|5027215",
            "entityData": {
                "type": "song",
                "id": "5027215",
                "provider": "itunes",
                "title": "Planet of the Blue",
                "artistName": "Billie Ray Martin",
            },
            "sections": [
                {
                    "links": [
                        {"platform": "appleMusic", "url": instrumental},
                        {"platform": "itunes", "url": original},
                        {"platform": "deezer", "url": deezer},
                    ],
                },
            ],
        },
    )

    links = partial(data).links

    assert [link.url for link in links] == [original, deezer]


def test_page_without_entity_has_links_only() -> None:
    data = page_data(page({"pageData": PAGE_DATA | {"entityData": None}}), "u")

    found = partial(data)

    assert found.candidate is None
    assert found.links[0].target is LinkTarget.TRACK


def test_ready_without_a_key() -> None:
    assert adapter([]).status().state is SourceState.READY
    assert adapter([]).pass_ is Pass.LINKS
    query = parse_query(SPOTIFY)
    assert adapter([]).resolves(query)
    assert not adapter([]).resolves(parse_query("Radiohead - Creep", EntityKind.TRACK))


@pytest.mark.parametrize(
    ("platform", "service"),
    [("appleMusic", "apple_music"), ("amazonMusic", "amazon_music"), ("itunes", "itunes_store"),
     ("youtubeMusic", "youtube_music"), ("spotify", "spotify")],
)  # fmt: skip
def test_service_names(platform: str, service: str) -> None:
    assert service_name(platform) == service
