from datetime import UTC, datetime

import httpx
import pytest

from deadwax.core import (
    EntityKind,
    IdKind,
    Link,
    LinkTarget,
    LookupContext,
    MetricKind,
    NotFoundError,
    Provenance,
    RelationKind,
    SourceError,
    SourceState,
    TagKind,
    TextKind,
    merge,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.soundcloud import SoundCloudAdapter

API = "https://api-v2.soundcloud.com"
HYPERDUB = {"id": 7, "username": "Hyperdub", "permalink_url": "https://soundcloud.com/hyperdub"}
BURIAL = {
    "id": 8,
    "username": "Burial",
    "permalink_url": "https://soundcloud.com/burial",
    "followers_count": 90000,
}
LISTENER = {"id": 10, "username": "listener", "followers_count": 12}
LABEL = {"id": 11, "username": "Small Label", "followers_count": 40, "verified": True}
TRACK = {
    "kind": "track",
    "id": 101,
    "title": "Burial - Archangel",
    "permalink_url": "https://soundcloud.com/hyperdub/burial-archangel",
    "description": "  From the album Untrue.  ",
    "genre": "Dubstep",
    "tag_list": 'dubstep "uk garage" Dubstep',
    "playback_count": 1000,
    "likes_count": 50,
    "reposts_count": 5,
    "release_date": "2007-11-05T00:00:00Z",
    "user": HYPERDUB,
    "publisher_metadata": {"isrc": "GBBPW0700012", "p_line": "2007 Hyperdub", "c_line": "© 2007"},
}
EDIT = {
    "kind": "track",
    "id": 102,
    "title": "Archangel (Someone's Bootleg)",
    "permalink_url": "https://soundcloud.com/someone/archangel-edit",
    "user": {"id": 9, "username": "Burial"},
    "publisher_metadata": None,
}
ALBUM = {
    "kind": "playlist",
    "id": 201,
    "title": "Untrue",
    "set_type": "album",
    "permalink_url": "https://soundcloud.com/burial/sets/untrue",
    "release_date": "2007-11-05",
    "likes_count": 9,
    "user": BURIAL,
    "publisher_metadata": {"artist": "Burial", "upc_or_ean": "5055300301234"},
}
PLAYLIST = {
    **ALBUM,
    "id": 202,
    "set_type": "",
    "permalink_url": "https://soundcloud.com/a/sets/mix",
}
PAGES = {
    TRACK["permalink_url"]: TRACK,
    EDIT["permalink_url"]: EDIT,
    ALBUM["permalink_url"]: ALBUM,
    PLAYLIST["permalink_url"]: PLAYLIST,
    "https://soundcloud.com/burial": {**BURIAL, "kind": "user"},
}


def make(
    status: int = 200,
    tracks: list[dict[str, object]] | None = None,
) -> tuple[SoundCloudAdapter, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if status != 200:
            return httpx.Response(status)
        if path == "/resolve":
            page = PAGES.get(request.url.params["url"])
            return httpx.Response(200, json=page) if page else httpx.Response(404)
        if path == "/search/tracks":
            return httpx.Response(200, json={"collection": [TRACK] if tracks is None else tracks})
        if path == "/search/albums":
            return httpx.Response(200, json={"collection": [PLAYLIST, ALBUM]})
        if path == "/tracks/101/reposters":
            return httpx.Response(200, json={"collection": [BURIAL, LISTENER, LABEL]})
        return httpx.Response(404)

    config = SourcesConfig.model_validate(
        {
            "soundcloud": {"rate": 1000, "client_id": "c1d"},
            "http": {"retries": 0, "escalation": "none"},
        },
    )
    return SoundCloudAdapter(config, HttpResources(transport=httpx.MockTransport(handler))), seen


@pytest.mark.asyncio
async def test_track_by_search() -> None:
    adapter, seen = make()
    query = parse_query("Burial - Archangel", EntityKind.TRACK)

    partial = await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()

    assert [r.url.path for r in seen] == ["/search/tracks", "/resolve", "/tracks/101/reposters"]
    assert {r.url.params["client_id"] for r in seen} == {"c1d"}
    assert seen[0].url.params["q"] == "Burial Archangel"

    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.artist, candidate.title, candidate.date) == (
        "Burial",
        "Archangel",
        "2007-11-05",
    )
    assert candidate.isrcs == ["GBBPW0700012"]
    assert candidate.copyrights == ["℗ 2007 Hyperdub", "© 2007"]
    assert candidate.ids == {IdKind.SOUNDCLOUD: "101"}
    assert [(t.name, t.kind) for t in partial.tags] == [
        ("Dubstep", TagKind.GENRE),
        ("uk garage", TagKind.TAG),
    ]
    [text] = partial.texts
    assert (text.kind, text.body, text.author, text.publication) == (
        TextKind.LABEL,
        "From the album Untrue.",
        "Hyperdub",
        "SoundCloud",
    )
    assert [(m.kind, m.value) for m in partial.metrics] == [
        (MetricKind.LISTENS, 1000),
        (MetricKind.LIKES, 50),
        (MetricKind.REPOSTS, 5),
    ]
    assert [(r.kind, r.target.name) for r in partial.relations] == [
        (RelationKind.REPOSTED_BY, "Burial"),
        (RelationKind.REPOSTED_BY, "Small Label"),
    ]
    assert [(link.target, link.url) for link in partial.links] == [
        (LinkTarget.TRACK, "https://soundcloud.com/hyperdub/burial-archangel"),
        (LinkTarget.OTHER, "https://soundcloud.com/hyperdub"),
    ]


@pytest.mark.asyncio
async def test_official_upload_beats_a_reupload() -> None:
    reupload = {
        **TRACK,
        "id": 103,
        "permalink_url": "https://soundcloud.com/fan/burial-archangel",
        "user": {"id": 12, "username": "fan"},
        "publisher_metadata": None,
        "release_date": None,
    }
    adapter, seen = make(tracks=[reupload, TRACK])
    query = parse_query("Burial - Archangel", EntityKind.TRACK)

    partial = await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()

    assert seen[1].url.params["url"] == "https://soundcloud.com/hyperdub/burial-archangel"
    assert partial.candidate is not None
    assert partial.candidate.date == "2007-11-05"


@pytest.mark.asyncio
async def test_album_url_resolves_without_reposters() -> None:
    adapter, seen = make()
    query = parse_query("https://soundcloud.com/burial/sets/untrue")

    assert query.kind is None
    assert adapter.resolves(query)
    partial = await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()

    assert [r.url.path for r in seen] == ["/resolve", "/playlists/201/reposters"]
    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.kind, candidate.artist, candidate.title) == (
        EntityKind.ALBUM,
        "Burial",
        "Untrue",
    )
    assert candidate.upcs == ["5055300301234"]
    assert not partial.relations
    assert not partial.texts
    assert [(m.kind, m.scope) for m in partial.metrics] == [(MetricKind.LIKES, "release")]
    assert [link.target for link in partial.links] == [LinkTarget.ALBUM, LinkTarget.ARTIST]


@pytest.mark.asyncio
async def test_album_search_skips_playlists() -> None:
    adapter, seen = make()
    query = parse_query("Burial - Untrue", EntityKind.ALBUM)

    partial = await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()

    assert seen[1].url.params["url"] == "https://soundcloud.com/burial/sets/untrue"
    assert partial.candidate is not None


@pytest.mark.asyncio
async def test_link_from_an_earlier_source() -> None:
    adapter, seen = make()
    query = parse_query("Burial - Archangel", EntityKind.TRACK)
    link = Link(
        service="soundcloud",
        url="https://soundcloud.com/hyperdub/burial-archangel",
        target=LinkTarget.TRACK,
        sources=[Provenance(source="musicbrainz")],
    )

    await adapter.lookup(query, LookupContext(query=query, links=[link]))
    await adapter.aclose()

    assert seen[0].url.path == "/resolve"


@pytest.mark.asyncio
async def test_merge_drops_an_edit() -> None:
    adapter, _ = make(tracks=[EDIT])
    query = parse_query("Burial - Archangel", EntityKind.TRACK)

    partial = await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()
    dossier = merge(query, [partial], generated_at=datetime.now(UTC))

    assert partial.candidate is not None
    assert partial.candidate.artist == "Burial"
    assert not dossier.tags
    assert not dossier.metrics
    assert not dossier.links
    assert [r.kind for r in dossier.relations] == [RelationKind.OTHER_VERSION]
    assert [d.field for d in dossier.identity.discrepancies] == ["version"]


@pytest.mark.asyncio
async def test_pages_that_are_not_records() -> None:
    adapter, _ = make()

    for url, reason in (
        ("https://soundcloud.com/a/sets/mix", "playlist, not a release"),
        ("https://soundcloud.com/burial", "a user, not a record"),
    ):
        query = parse_query(url)
        with pytest.raises(NotFoundError, match=reason):
            await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()


@pytest.mark.asyncio
async def test_not_found() -> None:
    adapter, _ = make(tracks=[])
    query = parse_query("Burial - Archangel", EntityKind.TRACK)
    nameless = parse_query("https://example.org/page")

    with pytest.raises(NotFoundError, match="no matching SoundCloud track"):
        await adapter.lookup(query, LookupContext(query=query))
    with pytest.raises(NotFoundError, match="neither"):
        await adapter.lookup(nameless, LookupContext(query=nameless))
    await adapter.aclose()


@pytest.mark.asyncio
async def test_rejected_client_id() -> None:
    adapter, _ = make(status=401)
    query = parse_query("Burial - Archangel", EntityKind.TRACK)

    with pytest.raises(SourceError, match="client_id stale") as raised:
        await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()

    assert raised.value.url is not None
    assert "c1d" not in raised.value.url


def test_missing_client_id_skips_the_source() -> None:
    status = SoundCloudAdapter(SourcesConfig(), HttpResources()).status()

    assert status.state is SourceState.MISSING_CREDENTIAL
    assert status.detail == "needs soundcloud.client_id"
