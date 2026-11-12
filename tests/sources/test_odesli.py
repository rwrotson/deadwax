import httpx
import pytest
from pydantic import SecretStr

from deadwax.core import (
    EntityKind,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Provenance,
    SourceState,
    parse_query,
)
from deadwax.sources import OdesliSettings, SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.odesli import OdesliAdapter, service_name

# Hand-written response in the shape Odesli documents; the keyless API was retired, so none
# could be recorded.
LINKS = {
    "entityUniqueId": "SPOTIFY_SONG::6LgJvl0Xdtc73RJ1mmpotq",
    "pageUrl": "https://song.link/s/6LgJvl0Xdtc73RJ1mmpotq",
    "entitiesByUniqueId": {
        "SPOTIFY_SONG::6LgJvl0Xdtc73RJ1mmpotq": {
            "id": "6LgJvl0Xdtc73RJ1mmpotq",
            "type": "song",
            "title": "Paranoid Android",
            "artistName": "Radiohead",
        }
    },
    "linksByPlatform": {
        "spotify": {"url": "https://open.spotify.com/track/6LgJvl0Xdtc73RJ1mmpotq"},
        "appleMusic": {"url": "https://geo.music.apple.com/us/album/_/1097861387?i=1097861770"},
        "youtubeMusic": {"url": "https://music.youtube.com/watch?v=fHiGbolFFGw"},
        "amazonMusic": {"url": "https://music.amazon.com/albums/B07ZR4PJVK"},
    },
}


def adapter(key: str | None, requests: list[httpx.Request]) -> OdesliAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=LINKS)

    settings = OdesliSettings(api_key=SecretStr(key) if key else None)
    config = SourcesConfig(odesli=settings)
    return OdesliAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_links_on_every_platform_from_a_curated_link() -> None:
    requests: list[httpx.Request] = []
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)
    spotify = Link(
        service="spotify",
        url="https://open.spotify.com/track/6LgJvl0Xdtc73RJ1mmpotq",
        target=LinkTarget.TRACK,
        sources=[Provenance(source="musicbrainz")],
    )
    odesli = adapter("s3cret", requests)

    partial = await odesli.lookup(query, LookupContext(query=query, links=[spotify]))
    await odesli.aclose()

    assert odesli.status().ready
    assert requests[0].url.params["key"] == "s3cret"
    assert requests[0].url.params["url"] == spotify.url
    assert partial.candidate is not None
    assert (partial.candidate.artist, partial.candidate.title) == ("Radiohead", "Paranoid Android")
    assert {link.service for link in partial.links} == {
        "spotify",
        "apple_music",
        "youtube_music",
        "amazon_music",
    }
    assert all(link.sources[0].url == LINKS["pageUrl"] for link in partial.links)


@pytest.mark.asyncio
async def test_query_url_is_the_seed_and_is_resolved() -> None:
    requests: list[httpx.Request] = []
    query = parse_query("https://open.spotify.com/track/6LgJvl0Xdtc73RJ1mmpotq")
    odesli = adapter("s3cret", requests)

    await odesli.lookup(query, LookupContext(query=query))

    assert odesli.resolves(query)
    assert requests[0].url.params["url"] == query.url


@pytest.mark.asyncio
async def test_without_a_seed_nothing_is_requested() -> None:
    requests: list[httpx.Request] = []
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)

    with pytest.raises(NotFoundError, match="no streaming URL"):
        await adapter("s3cret", requests).lookup(query, LookupContext(query=query))

    assert requests == []


def test_missing_key_and_disabled_states() -> None:
    disabled = SourcesConfig(odesli=OdesliSettings(enabled=False, api_key=SecretStr("k")))

    status = adapter(None, []).status()

    assert status.state is SourceState.MISSING_CREDENTIAL
    assert status.detail is not None
    assert "odesli.api_key" in status.detail
    assert OdesliAdapter(disabled, HttpResources()).status().state is SourceState.DISABLED


@pytest.mark.parametrize(
    ("platform", "service"),
    [("spotify", "spotify"), ("appleMusic", "apple_music"), ("amazonStore", "amazon_store")],
)
def test_platform_names(platform: str, service: str) -> None:
    assert service_name(platform) == service
