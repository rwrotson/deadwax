from collections.abc import Callable
from typing import cast

import httpx
import pytest

from deadwax import (
    CatalogExpansion,
    Deadwax,
    EntityType,
    ErrorKind,
    IdKind,
    LookupConfig,
    ReleaseTrack,
    VersionKind,
)
from deadwax.core import InvalidQueryError

RELEASE = "3c8cbdc8-555f-3987-8f03-6baf9488d1b0"
WORK = "2be60b42-e477-3d91-b31f-a61a00780158"


@pytest.mark.asyncio
async def test_musicbrainz_release_keeps_track_and_recording_distinct(config: LookupConfig) -> None:
    track = {
        "title": "As printed",
        "number": "B2",
        "id": "track-id",
        "artist-credit": [
            {"name": "Alias", "joinphrase": " feat. ", "artist": {"id": "a", "name": "Canonical"}},
            {"name": "Guest", "artist": {"id": "b", "name": "Guest"}},
        ],
        "recording": {"id": "recording-id", "title": "Canonical title", "isrcs": ["GBAYE9700142"]},
    }

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "musicbrainz.org"
        assert request.url.path == f"/ws/2/release/{RELEASE}"
        assert request.url.params.get("inc") == "recordings+artist-credits+isrcs"
        return httpx.Response(
            200,
            json={
                "id": RELEASE,
                "title": "Compilation",
                "media": [
                    {"position": 1, "track-count": 9, "tracks": []},
                    {
                        "position": 2,
                        "track-count": 2,
                        "tracks": [
                            track,
                            {
                                "title": "Second",
                                "number": "B3",
                                "recording": {"id": "second-id", "title": "Second"},
                            },
                        ],
                    },
                ],
            },
        )

    async with Deadwax(config, transport=httpx.MockTransport(respond)) as client:
        result = await client.release_tracklist(IdKind.MUSICBRAINZ_RELEASE, RELEASE, limit=1)
    assert result.entity is not None
    assert result.entity.ids == {IdKind.MUSICBRAINZ_RELEASE: RELEASE}
    assert result.truncated
    assert [error.kind for error in result.errors] == [ErrorKind.NOT_FOUND]
    (item,) = result.items
    assert (item.title, item.artist_credit, item.medium, item.position) == (
        "As printed",
        "Alias feat. Guest",
        2,
        "B2",
    )
    assert item.ids == {IdKind.MUSICBRAINZ_TRACK: "track-id"}
    assert item.recording.name == "Canonical title"
    assert item.recording.ids == {IdKind.MUSICBRAINZ_RECORDING: "recording-id"}
    assert item.isrcs == ["GBAYE9700142"]
    assert (item.sources[0].source, item.sources[0].url) == ("musicbrainz", result.entity.url)
    assert type(result).model_validate_json(result.model_dump_json()) == result


@pytest.mark.asyncio
async def test_discogs_uses_specific_recorded_release(
    replay: Callable[..., httpx.MockTransport],
    config: LookupConfig,
) -> None:
    seen: list[str] = []
    async with Deadwax(config, transport=replay("discogs_url", seen)) as client:
        result = await client.release_tracklist(IdKind.DISCOGS_RELEASE, "4950798", limit=2)

    assert seen == ["GET https://api.discogs.com/releases/4950798"]
    assert result.entity is not None
    assert result.entity.ids == {IdKind.DISCOGS_RELEASE: "4950798"}
    assert [item.position for item in result.items] == ["A1", "A2"]
    assert all(item.artist_credit == "Radiohead" for item in result.items)
    assert all(item.sources[0].url == result.entity.url for item in result.items)
    assert result.truncated
    assert not result.errors


@pytest.mark.asyncio
async def test_discogs_index_parts_use_credited_names(config: LookupConfig) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/releases/25"
        return httpx.Response(
            200,
            json={
                "id": 25,
                "title": "Compilation",
                "artists": [{"name": "Various"}],
                "tracklist": [
                    {"type_": "heading", "title": "Side A"},
                    {
                        "type_": "index",
                        "title": "Suite",
                        "artists": [{"name": "Canonical (2)", "anv": "Printed"}],
                        "sub_tracks": [
                            {"position": "A1.1", "title": "Part 1"},
                            {"position": "A1.2", "title": "Part 2", "artists": [{"name": "Guest"}]},
                        ],
                    },
                ],
            },
        )

    async with Deadwax(config, transport=httpx.MockTransport(respond)) as client:
        result = await client.release_tracklist(IdKind.DISCOGS_RELEASE, "25")
    assert [(track.position, track.title, track.artist_credit) for track in result.items] == [
        ("A1.1", "Part 1", "Printed"),
        ("A1.2", "Part 2", "Guest"),
    ]
    assert all(not track.ids and not track.recording.ids for track in result.items)
    assert not result.truncated


@pytest.mark.asyncio
async def test_musicbrainz_work_keeps_performance_attributes(config: LookupConfig) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/ws/2/work/{WORK}"
        assert request.url.params.get("inc") == "recording-rels+artist-credits"
        return httpx.Response(
            200,
            json={
                "id": WORK,
                "title": "Work name",
                "relations": [
                    {
                        "type": "performance",
                        "target-type": "recording",
                        "attributes": ["cover", "live"],
                        "recording": {"id": "a", "title": "Performance title"},
                    },
                    {
                        "type": "performance",
                        "target-type": "recording",
                        "recording": {"id": "b", "title": "Performance title (remix)"},
                    },
                    {
                        "type": "samples",
                        "target-type": "recording",
                        "recording": {"id": "c", "title": "Another work"},
                    },
                ],
            },
        )

    async with Deadwax(config, transport=httpx.MockTransport(respond)) as client:
        result = await client.work_performances(WORK, limit=2)
    assert result.entity is not None
    assert result.entity.type is EntityType.WORK
    assert result.entity.ids == {IdKind.MUSICBRAINZ_WORK: WORK}
    assert result.entity.name == "Work name"
    assert not result.truncated
    assert not result.errors
    first, second = result.items
    assert first.recording.name == "Performance title"
    assert first.recording.ids == {IdKind.MUSICBRAINZ_RECORDING: "a"}
    assert first.attributes == ["cover", "live"]
    assert first.version.kind is VersionKind.LIVE
    assert second.version.kind is VersionKind.REMIX
    assert first.sources[0].url == result.entity.url


@pytest.mark.asyncio
async def test_catalog_reports_empty_disabled_and_missing_sources() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/ws/2/work/{WORK}":
            return httpx.Response(200, json={"id": WORK, "title": "Work"})
        if request.url.path == f"/ws/2/release/{RELEASE}":
            return httpx.Response(404)
        pytest.fail(f"unexpected request to {request.url}")

    config = LookupConfig.model_validate(
        {
            "sources": {"discogs": {"enabled": False}, "musicbrainz": {"rate": 1000}},
        }
    )
    async with Deadwax(config, transport=httpx.MockTransport(respond)) as client:
        work = await client.work_performances(WORK)
        missing = await client.release_tracklist(IdKind.MUSICBRAINZ_RELEASE, RELEASE)
        disabled = await client.release_tracklist(IdKind.DISCOGS_RELEASE, "25")
    assert work.entity is not None
    assert not work.items
    assert [error.kind for error in work.errors] == [ErrorKind.NOT_FOUND]
    assert type(missing) is CatalogExpansion[ReleaseTrack]
    assert missing.entity is None
    assert not missing.items
    assert [error.kind for error in missing.errors] == [ErrorKind.NOT_FOUND]
    assert disabled.entity is None
    assert not disabled.items
    assert [(error.source, error.kind) for error in disabled.errors] == [
        ("discogs", ErrorKind.SKIPPED)
    ]


@pytest.mark.asyncio
async def test_catalog_validates_limits_and_exact_ids() -> None:
    client = Deadwax()
    with pytest.raises(RuntimeError, match="not open"):
        await client.work_performances(WORK)
    async with client:
        with pytest.raises(InvalidQueryError, match="limit"):
            await client.work_performances(WORK, limit=101)
        with pytest.raises(InvalidQueryError, match="limit"):
            await client.work_performances(WORK, limit=cast(int, 1.5))
        with pytest.raises(InvalidQueryError, match="UUID"):
            await client.work_performances("../not-a-work")
        with pytest.raises(InvalidQueryError, match="release ID"):
            await client.release_tracklist(IdKind.DISCOGS_MASTER, "25")
        with pytest.raises(InvalidQueryError, match="positive Discogs release ID"):
            await client.release_tracklist(IdKind.DISCOGS_RELEASE, "0")
