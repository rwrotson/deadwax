import httpx
import pytest

from deadwax.core import (
    EntityKind,
    Identity,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Provenance,
    Sourced,
    SourceError,
    SourceState,
)
from deadwax.sources import LookupConfig, parse_query
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.youtube import YouTubeAdapter


def video(video_id: str, title: str, channel: str) -> dict[str, object]:
    return {"id": {"videoId": video_id}, "snippet": {"title": title, "channelTitle": channel}}


VIDEOS: list[dict[str, object]] = [
    video("fan", "Radiohead - Paranoid Android", "Some Fan"),
    video("live", "Radiohead - Paranoid Android (Live at Glastonbury 1997)", "Archive"),
    video("cover", "Paranoid Android (cover)", "A Cellist"),
    video("vevo", "Radiohead - Paranoid Android (Official Music Video)", "RadioheadVEVO"),
    video("topic", "Paranoid Android", "Radiohead - Topic"),
    video("other", "Radiohead - Creep", "Radiohead - Topic"),
    {"id": {"channelId": "c"}, "snippet": {"title": "Radiohead - Paranoid Android"}},
]
PLAYLISTS = [
    {
        "id": {"playlistId": "PL1"},
        "snippet": {"title": "Album - OK Computer", "channelTitle": "Radiohead - Topic"},
    },
    {"id": {"playlistId": "PL2"}, "snippet": {"title": "best of 1997", "channelTitle": "Someone"}},
    {
        "id": {"playlistId": "PL3"},
        "snippet": {"title": "Radiohead - OK Computer (Full Album HQ)", "channelTitle": "Fan"},
    },
    {
        "id": {"playlistId": "PL4"},
        "snippet": {"title": "Radiohead - OK Computer OKNOTOK (1997)", "channelTitle": "Fan"},
    },
]


def make(
    status: int = 200,
    items: list[dict[str, object]] | None = None,
) -> tuple[YouTubeAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": {"code": status}})
        found = PLAYLISTS if request.url.params["type"] == "playlist" else VIDEOS
        return httpx.Response(200, json={"items": found if items is None else items})

    config = LookupConfig.model_validate(
        {
            "sources": {"youtube": {"rate": 1000, "api_key": "k3y"}},
            "http": {"retries": 0, "escalation": []},
        },
    )
    return YouTubeAdapter(config, HttpResources(transport=httpx.MockTransport(handler))), seen


@pytest.mark.asyncio
async def test_official_uploads_of_the_record_come_first() -> None:
    adapter, seen = make()
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)

    partial = await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()

    params = seen[0].url.params
    assert (params["type"], params["videoCategoryId"], params["key"]) == ("video", "10", "k3y")
    assert params["q"] == "Radiohead Paranoid Android"
    assert [link.url.rsplit("=", 1)[1] for link in partial.links] == ["topic", "vevo", "fan"]
    assert {link.target for link in partial.links} == {LinkTarget.TRACK}
    assert {link.service for link in partial.links} == {"youtube"}
    assert partial.links[0].sources == [
        Provenance(source="youtube", url="https://www.youtube.com/watch?v=topic"),
    ]


@pytest.mark.asyncio
async def test_contributes_nothing_but_links() -> None:
    adapter, _ = make()
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)

    partial = await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()

    assert partial.links
    assert partial.candidate is None
    facts = (partial.tags, partial.credits, partial.texts, partial.relations, partial.metrics)
    assert not any(facts)


@pytest.mark.asyncio
async def test_another_version_is_dropped() -> None:
    adapter, _ = make(items=VIDEOS[1:3])
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)

    with pytest.raises(NotFoundError, match="no YouTube upload"):
        await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()


@pytest.mark.asyncio
async def test_album_playlists_from_the_identity_of_a_url_query() -> None:
    adapter, seen = make()
    query = parse_query("https://open.spotify.com/album/x")
    sources = [Provenance(source="spotify")]
    context = LookupContext(
        query=query,
        identity=Identity(
            kind=EntityKind.ALBUM,
            artist=Sourced(value="Radiohead", sources=sources),
            title=Sourced(value="OK Computer", sources=sources),
        ),
    )

    partial = await adapter.lookup(query, context)
    await adapter.aclose()

    assert seen[0].url.params["type"] == "playlist"
    assert "videoCategoryId" not in seen[0].url.params
    assert [(link.url, link.target) for link in partial.links] == [
        ("https://www.youtube.com/playlist?list=PL1", LinkTarget.ALBUM),
        ("https://www.youtube.com/playlist?list=PL3", LinkTarget.ALBUM),
    ]


@pytest.mark.asyncio
async def test_refused_search_names_quota_or_key() -> None:
    adapter, _ = make(status=403)
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)

    with pytest.raises(SourceError, match="quota") as raised:
        await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()

    assert raised.value.url is not None
    assert "k3y" not in raised.value.url


@pytest.mark.asyncio
async def test_without_a_record_name() -> None:
    adapter, seen = make()
    query = parse_query("https://example.org/page")

    with pytest.raises(NotFoundError, match="neither"):
        await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()

    assert seen == []


def test_missing_key_skips_the_source() -> None:
    status = YouTubeAdapter(LookupConfig(), HttpResources()).status()

    assert status.state is SourceState.MISSING_CREDENTIAL
    assert status.detail == "needs sources.youtube.api_key"
