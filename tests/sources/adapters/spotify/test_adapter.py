import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from deadwax.core import (
    EntityKind,
    Identity,
    IdKind,
    Link,
    LinkTarget,
    LookupContext,
    MetricKind,
    NotFoundError,
    Provenance,
    RelationKind,
    Sourced,
    SourceError,
    SourceState,
    merge,
)
from deadwax.sources import CacheSettings, LookupConfig, parse_query
from deadwax.sources._http import HttpResources, open_cache
from deadwax.sources.adapters.spotify import SpotifyAdapter
from deadwax.sources.adapters.spotify.models import Copyright, SearchResults
from deadwax.sources.adapters.spotify.parse import copyright_line, track_hits

API = "https://api.spotify.com/v1"
ARTIST = {
    "id": "a1",
    "name": "Radiohead",
    "external_urls": {"spotify": "https://open.spotify.com/artist/a1"},
}
ALBUM_REF = {
    "id": "al1",
    "name": "OK Computer",
    "href": f"{API}/albums/al1",
    "album_type": "album",
    "release_date": "1997-05-21",
    "artists": [ARTIST],
    "external_urls": {"spotify": "https://open.spotify.com/album/al1"},
}
ALBUM = {
    **ALBUM_REF,
    "label": "XL Recordings",
    "popularity": 80,
    "copyrights": [
        {"text": "1997 XL Recordings Ltd", "type": "C"},
        {"text": "℗ 1997 XL Recordings Ltd", "type": "P"},
    ],
    "external_ids": {"upc": "634904078164"},
}


def track(track_id: str, name: str, **fields: object) -> dict[str, object]:
    return {
        "id": track_id,
        "name": name,
        "href": f"{API}/tracks/{track_id}",
        "artists": [ARTIST],
        "album": ALBUM_REF,
        "popularity": 70,
        "preview_url": None,
        "external_ids": {"isrc": "GBAYE9701376"},
        "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
        **fields,
    }


TRACKS = {
    "t1": track("t1", "Paranoid Android", preview_url="https://p.scdn.co/mp3-preview/x"),
    "t2": track("t2", "Paranoid Android - Live", external_ids={}),
}


class Server:
    def __init__(self, token_status: int = 200, *, only_live: bool = False) -> None:
        self.token_status = token_status
        self.only_live = only_live
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "accounts.spotify.com":
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_client"})
            return httpx.Response(200, json={"access_token": "abc", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer abc"
        if path.startswith("/v1/tracks/"):
            found = TRACKS.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=found) if found else httpx.Response(404)
        if path == "/v1/albums/al1":
            return httpx.Response(200, json=ALBUM)
        if path == "/v1/search":
            return self.search(request.url.params["q"], request.url.params["type"])
        return httpx.Response(404)

    def search(self, q: str, kind: str) -> httpx.Response:
        if kind == "album":
            return httpx.Response(200, json={"albums": {"items": [None, ALBUM_REF]}})
        if q.startswith("isrc:"):
            return httpx.Response(200, json={"tracks": {"items": [TRACKS["t1"]]}})
        if "Nothing" in q:
            return httpx.Response(200, json={"tracks": {"items": []}})
        live_only = self.only_live or "Live" in q
        items = [TRACKS["t2"]] if live_only else [TRACKS["t2"], TRACKS["t1"]]
        return httpx.Response(200, json={"tracks": {"items": items}})


def config(**changes: object) -> LookupConfig:
    return LookupConfig.model_validate(
        {
            "sources": {"spotify": {"rate": 1000, "client_id": "id", "client_secret": "secret"}},
            "http": {"retries": 0, "escalation": []},
            **changes,
        },
    )


def make(server: Server, settings: LookupConfig | None = None) -> SpotifyAdapter:
    resources = HttpResources(transport=httpx.MockTransport(server))
    return SpotifyAdapter(settings or config(), resources)


def context(text: str, kind: EntityKind, **identity: object) -> LookupContext:
    return LookupContext(
        query=parse_query(text, kind),
        identity=Identity.model_validate(identity),
    )


@pytest.mark.asyncio
async def test_track_by_search_with_album_facts() -> None:
    server = Server()
    adapter = make(server)
    found = context("Radiohead - Paranoid Android", EntityKind.TRACK)

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    token = server.requests[0]
    assert token.method == "POST"
    assert token.content == b"grant_type=client_credentials"
    assert token.headers["authorization"] == "Basic " + base64.b64encode(b"id:secret").decode()
    search = server.requests[1].url.params
    assert search["q"] == 'track:"Paranoid Android" artist:"Radiohead"'
    assert search["limit"] == "10"
    assert [r.url.path for r in server.requests[2:]] == ["/v1/tracks/t1", "/v1/albums/al1"]

    candidate = partial.candidate
    assert candidate is not None
    assert (candidate.artist, candidate.title, candidate.date) == (
        "Radiohead",
        "Paranoid Android",
        "1997-05-21",
    )
    assert candidate.isrcs == ["GBAYE9701376"]
    assert candidate.ids == {IdKind.SPOTIFY: "t1"}
    assert [label.name for label in candidate.labels] == ["XL Recordings"]
    assert candidate.copyrights == ["© 1997 XL Recordings Ltd", "℗ 1997 XL Recordings Ltd"]
    assert [(m.kind, m.value, m.scale) for m in partial.metrics] == [
        (MetricKind.POPULARITY, 70, 100),
    ]
    assert [(link.target, link.url) for link in partial.links] == [
        (LinkTarget.TRACK, "https://open.spotify.com/track/t1"),
        (LinkTarget.ALBUM, "https://open.spotify.com/album/al1"),
        (LinkTarget.ARTIST, "https://open.spotify.com/artist/a1"),
    ]
    assert partial.links[0].preview_url == "https://p.scdn.co/mp3-preview/x"


@pytest.mark.asyncio
async def test_live_query_picks_the_live_track() -> None:
    adapter = make(Server())
    found = context("Radiohead - Paranoid Android (Live)", EntityKind.TRACK)

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    assert partial.candidate is not None
    assert partial.candidate.title == "Paranoid Android - Live"
    assert partial.candidate.isrcs == []


@pytest.mark.asyncio
async def test_merge_drops_another_version() -> None:
    adapter = make(Server(only_live=True))
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)

    partial = await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()
    dossier = merge(query, [partial], generated_at=datetime.now(UTC))

    assert not dossier.links
    assert not dossier.metrics
    assert [r.kind for r in dossier.relations] == [RelationKind.OTHER_VERSION]
    assert [d.field for d in dossier.identity.discrepancies] == ["version"]


@pytest.mark.asyncio
async def test_url_query_reads_the_track() -> None:
    server = Server()
    adapter = make(server)
    query = parse_query("https://open.spotify.com/track/t1")

    assert adapter.resolves(query)
    partial = await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()

    assert [r.url.path for r in server.requests[1:]] == ["/v1/tracks/t1", "/v1/albums/al1"]
    assert partial.candidate is not None
    assert partial.candidate.ids == {IdKind.SPOTIFY: "t1"}


@pytest.mark.asyncio
async def test_known_link_and_isrc_skip_the_search() -> None:
    server = Server()
    adapter = make(server)
    linked = context("Radiohead - Paranoid Android", EntityKind.TRACK).model_copy(
        update={
            "links": [
                Link(
                    service="spotify",
                    url="https://open.spotify.com/album/al1",
                    target=LinkTarget.ALBUM,
                    sources=[Provenance(source="musicbrainz")],
                ),
                Link(
                    service="spotify",
                    url="https://open.spotify.com/track/t1",
                    target=LinkTarget.TRACK,
                    sources=[Provenance(source="musicbrainz")],
                ),
            ],
        },
    )
    by_isrc = context(
        "Radiohead - Paranoid Android",
        EntityKind.TRACK,
        isrcs=[{"value": "GBAYE9701376", "sources": [{"source": "musicbrainz"}]}],
    )

    await adapter.lookup(linked.query, linked)
    await adapter.lookup(by_isrc.query, by_isrc)
    await adapter.aclose()

    paths = [(r.url.path, r.url.params.get("q")) for r in server.requests[1:]]
    assert paths == [
        ("/v1/tracks/t1", None),
        ("/v1/albums/al1", None),
        ("/v1/search", "isrc:GBAYE9701376"),
        ("/v1/tracks/t1", None),
        ("/v1/albums/al1", None),
    ]
    assert len([r for r in server.requests if r.url.host == "accounts.spotify.com"]) == 1


@pytest.mark.asyncio
async def test_codes_without_a_key_take_the_first_hit() -> None:
    server = Server()
    adapter = make(server)
    query = parse_query("https://open.spotify.com/intl-de/album/zz")
    found = LookupContext(
        query=query.model_copy(update={"ids": {}}),
        identity=Identity(
            upcs=[Sourced(value="634904078164", sources=[Provenance(source="musicbrainz")])],
        ),
    )

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    assert server.requests[1].url.params["q"] == "upc:634904078164"
    assert partial.candidate is not None
    assert partial.candidate.kind is EntityKind.ALBUM
    assert partial.candidate.upcs == ["634904078164"]
    assert [m.scope for m in partial.metrics] == ["release"]


@pytest.mark.asyncio
async def test_album_by_search() -> None:
    server = Server()
    adapter = make(server)
    found = context("Radiohead - OK Computer", EntityKind.ALBUM)

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    assert server.requests[1].url.params["q"] == 'album:"OK Computer" artist:"Radiohead"'
    assert partial.candidate is not None
    assert partial.candidate.ids == {IdKind.SPOTIFY: "al1"}
    assert [link.target for link in partial.links] == [LinkTarget.ALBUM, LinkTarget.ARTIST]


@pytest.mark.asyncio
async def test_not_found() -> None:
    adapter = make(Server())
    found = context("Radiohead - Nothing", EntityKind.TRACK)
    missing = LookupContext(query=parse_query("https://open.spotify.com/track/zz"))

    with pytest.raises(NotFoundError, match="no matching Spotify track"):
        await adapter.lookup(found.query, found)
    with pytest.raises(NotFoundError):
        await adapter.lookup(missing.query, missing)
    url_only = LookupContext(query=parse_query("https://example.org/x"))
    with pytest.raises(NotFoundError, match="neither"):
        await adapter.lookup(url_only.query, url_only)
    await adapter.aclose()


@pytest.mark.asyncio
async def test_rejected_credentials() -> None:
    adapter = make(Server(token_status=400))
    found = context("Radiohead - Paranoid Android", EntityKind.TRACK)

    with pytest.raises(SourceError, match="refused the client credentials"):
        await adapter.lookup(found.query, found)
    await adapter.aclose()


@pytest.mark.asyncio
async def test_missing_token_endpoint_is_not_found() -> None:
    adapter = make(Server(token_status=404))
    found = context("Radiohead - Paranoid Android", EntityKind.TRACK)

    with pytest.raises(NotFoundError):
        await adapter.lookup(found.query, found)
    await adapter.aclose()


@pytest.mark.asyncio
async def test_token_is_never_cached(tmp_path: Path) -> None:
    settings = config(cache={"path": str(tmp_path / "cache.sqlite")})
    cache = open_cache(CacheSettings(path=tmp_path / "cache.sqlite"))
    assert cache is not None
    server = Server()
    found = context("Radiohead - Paranoid Android", EntityKind.TRACK)

    for _ in range(2):
        resources = HttpResources(cache=cache, transport=httpx.MockTransport(server))
        adapter = SpotifyAdapter(settings, resources)
        await adapter.lookup(found.query, found)
        await adapter.aclose()
    cache.close()

    hosts = [r.url.host for r in server.requests]
    assert hosts.count("accounts.spotify.com") == 2
    assert hosts.count("api.spotify.com") == 3


def test_missing_credentials_skip_the_source() -> None:
    adapter = SpotifyAdapter(
        LookupConfig.model_validate({"sources": {"spotify": {"client_id": "id"}}}),
        HttpResources(),
    )

    status = adapter.status()

    assert status.state is SourceState.MISSING_CREDENTIAL
    assert status.detail == "needs sources.spotify.client_id and sources.spotify.client_secret"


def test_copyright_marks() -> None:
    assert copyright_line(Copyright(text="2000 Label", type="P")) == "℗ 2000 Label"
    assert copyright_line(Copyright(text="(C) 2000 Label", type="C")) == "(C) 2000 Label"
    assert copyright_line(Copyright(text=" 2000 Label ")) == "2000 Label"


def test_search_items_may_be_null() -> None:
    body = json.dumps({"tracks": {"items": [None]}})

    assert track_hits(SearchResults.model_validate_json(body)) == []
