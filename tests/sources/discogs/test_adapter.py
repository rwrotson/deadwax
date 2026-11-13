import json
from collections.abc import Callable, Mapping

import httpx
import pytest
from pydantic import SecretStr

from deadwax.core import (
    ConfigurationError,
    EntityKind,
    ErrorKind,
    ExternalId,
    Identity,
    IdKind,
    LookupContext,
    NotFoundError,
    Provenance,
    Query,
    RelationKind,
    SourceState,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import Fetcher, HttpResources
from deadwax.sources.config import Escalation, HttpSettings
from deadwax.sources.discogs import DiscogsAdapter
from deadwax.sources.discogs.adapter import ANONYMOUS_RATE, DEFAULT_USER_AGENT

API = "https://api.discogs.com"
PAGE = "https://www.discogs.com/release/10"
TRACKS = [{"position": "A1", "title": "Song"}, {"position": "A2", "title": "Other"}]
ARTISTS = [{"id": 3, "name": "Band"}]
MASTER = {"id": 1, "title": "Record", "main_release": 10, "artists": ARTISTS,
          "genres": ["Electronic"], "styles": ["Ambient"], "notes": "Master note"}  # fmt: skip
RELEASE = {"id": 10, "title": "Record", "master_id": 1, "released": "2020-02-03",
           "artists": ARTISTS, "labels": [{"id": 5, "name": "Label", "catno": "L1"}],
           "tracklist": TRACKS, "notes": "Release note"}  # fmt: skip
REVIEWS = (
    b'<script type="application/ld+json">{"@type": "MusicRelease", "review": '
    b'[{"reviewBody": "Good", "author": {"name": "fan"}}]}</script>'
)

type Route = tuple[int, object]


def routes(**changes: Route) -> dict[str, Route]:
    base: dict[str, Route] = {
        f"{API}/masters/1": (200, MASTER),
        f"{API}/releases/10": (200, RELEASE),
        f"{API}/masters/1/versions": (200, {"versions": [{"id": 11, "title": "Record"}]}),
        f"{API}/artists/3": (200, {"id": 3, "name": "Band", "members": [{"id": 4, "name": "M"}]}),
        f"{API}/labels/5/releases": (200, {"releases": [{"id": 12, "title": "Next"}]}),
        PAGE: (200, REVIEWS),
    }
    return base | {key.replace("__", "/"): value for key, value in changes.items()}


def make(
    table: Mapping[str, Route],
    *,
    token: str | None = None,
    seen: list[httpx.Request] | None = None,
    search: Callable[[httpx.Request], Route] | None = None,
    **http: object,
) -> DiscogsAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        url = str(request.url.copy_with(query=None))
        if url == f"{API}/database/search" and search is not None:
            status, body = search(request)
        else:
            status, body = table.get(url, (404, {"message": "not found"}))
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return httpx.Response(status, content=content)

    config = SourcesConfig.model_validate(
        {
            "discogs": {"rate": 1000, "token": token},
            "http": {"retries": 0, "escalation": [], **http},
        },
    )
    return DiscogsAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


def with_ids(query: Query, **ids: str) -> LookupContext:
    external = [
        ExternalId(kind=IdKind(kind), value=value, sources=[Provenance(source="musicbrainz")])
        for kind, value in ids.items()
    ]
    return LookupContext(query=query, identity=Identity(external_ids=external))


ALBUM = parse_query("Band - Record", EntityKind.ALBUM)
TRACK = parse_query("Band - Song", EntityKind.TRACK)


@pytest.mark.asyncio
async def test_album_by_master_id_from_an_earlier_pass() -> None:
    seen: list[httpx.Request] = []
    adapter = make(routes(), seen=seen)

    partial = await adapter.lookup(ALBUM, with_ids(ALBUM, discogs_master="1"))

    assert partial.candidate is not None
    assert partial.candidate.ids[IdKind.DISCOGS_RELEASE] == "10"
    assert [t.title for t in partial.texts if t.title] == ["Master notes", "Release notes"]
    assert [t.author for t in partial.texts if t.author] == ["fan"]
    kinds = {r.kind for r in partial.relations}
    assert {RelationKind.OTHER_VERSION, RelationKind.MEMBER, RelationKind.LABEL_RELEASE} <= kinds
    api = [r for r in seen if r.url.host == "api.discogs.com"]
    assert {r.headers["user-agent"] for r in api} == {DEFAULT_USER_AGENT}
    assert all("authorization" not in r.headers for r in seen)
    page = next(r for r in seen if r.url.host == "www.discogs.com")
    assert page.headers["user-agent"].startswith("Mozilla/5.0")
    await adapter.aclose()


@pytest.mark.asyncio
async def test_release_url_reads_its_master_for_the_group_facts() -> None:
    query = parse_query("https://www.discogs.com/release/10-Band-Record")
    adapter = make(routes())

    partial = await adapter.lookup(query, LookupContext(query=query))

    assert adapter.resolves(query)
    assert partial.candidate is not None
    assert partial.candidate.url == "https://www.discogs.com/master/1"


@pytest.mark.asyncio
async def test_release_without_master() -> None:
    release = RELEASE | {"master_id": None}
    adapter = make(routes(**{f"{API}/releases/10": (200, release)}))

    partial = await adapter.lookup(ALBUM, with_ids(ALBUM, discogs_release="10"))

    assert partial.candidate is not None
    assert RelationKind.OTHER_VERSION not in {r.kind for r in partial.relations}


@pytest.mark.asyncio
async def test_master_without_main_release() -> None:
    master = MASTER | {"main_release": None}
    adapter = make(routes(**{f"{API}/masters/1": (200, master)}))

    with pytest.raises(NotFoundError, match="no main release"):
        await adapter.lookup(ALBUM, with_ids(ALBUM, discogs_master="1"))


@pytest.mark.asyncio
async def test_without_ids_or_token_the_search_is_skipped() -> None:
    adapter = make(routes())

    partial = await adapter.lookup(ALBUM, LookupContext(query=ALBUM))

    assert partial.candidate is None
    assert [(e.kind, e.reason) for e in partial.errors] == [
        (ErrorKind.SKIPPED, "search needs discogs.token, and earlier sources found no Discogs ID"),
    ]
    assert adapter.status().state is SourceState.READY
    assert adapter.status().detail == "no discogs.token: no search"


@pytest.mark.asyncio
async def test_nothing_to_search_for() -> None:
    query = Query(url="https://example.com/x")

    with pytest.raises(NotFoundError, match="neither the query"):
        await make(routes(), token="t").lookup(query, LookupContext(query=query))


@pytest.mark.asyncio
async def test_track_search_with_a_token_finds_compilations() -> None:
    seen: list[httpx.Request] = []

    def search(request: httpx.Request) -> Route:
        if request.url.params.get("format") == "Compilation":
            hits = [{"id": 20, "type": "release", "title": "Various - Hits", "master_id": 21}]
            return 200, {"results": hits}
        return 200, {"results": [{"id": 10, "type": "release", "title": "Band - Record",
                                  "master_id": 1}]}  # fmt: skip

    adapter = make(routes(), token="t0ken", seen=seen, search=search)

    partial = await adapter.lookup(TRACK, LookupContext(query=TRACK))

    assert partial.candidate is not None
    assert (partial.candidate.kind, partial.candidate.title) == (EntityKind.TRACK, "Song")
    kinds = {r.kind for r in partial.relations}
    assert {RelationKind.COMPILATION, RelationKind.APPEARS_ON} <= kinds
    assert seen[0].headers["authorization"] == "Discogs token=t0ken"
    assert seen[0].url.params["track"] == "Song"
    assert adapter.status().detail is None


@pytest.mark.asyncio
async def test_album_search_finds_a_master() -> None:
    def search(request: httpx.Request) -> Route:
        assert request.url.params["type"] == "master"
        return 200, {"results": [{"id": 1, "type": "master", "title": "Band - Record"}]}

    partial = await make(routes(), token="t", search=search).lookup(
        ALBUM,
        LookupContext(query=ALBUM),
    )

    assert partial.candidate is not None
    assert partial.candidate.ids[IdKind.DISCOGS_MASTER] == "1"


@pytest.mark.asyncio
async def test_search_without_a_match() -> None:
    adapter = make(routes(), token="t", search=lambda _: (200, {"results": []}))

    with pytest.raises(NotFoundError, match="no matching Discogs release"):
        await adapter.lookup(ALBUM, LookupContext(query=ALBUM))


@pytest.mark.asyncio
async def test_release_search_without_master() -> None:
    def search(_: httpx.Request) -> Route:
        return 200, {"results": [{"id": 10, "type": "release", "title": "Band - Record"}]}

    partial = await make(routes(), token="t", search=search).lookup(
        TRACK,
        LookupContext(query=TRACK),
    )

    assert partial.candidate is not None


@pytest.mark.asyncio
async def test_track_not_on_the_release() -> None:
    query = parse_query("Band - Missing", EntityKind.TRACK)

    with pytest.raises(NotFoundError, match="not on the Discogs release"):
        await make(routes()).lookup(query, with_ids(query, discogs_master="1"))


@pytest.mark.asyncio
async def test_release_without_artist_or_label() -> None:
    release = RELEASE | {"artists": [{"name": "Band"}], "labels": []}
    adapter = make(routes(**{f"{API}/releases/10": (200, release)}))

    partial = await adapter.lookup(ALBUM, with_ids(ALBUM, discogs_release="10"))

    kinds = {r.kind for r in partial.relations}
    assert RelationKind.MEMBER not in kinds
    assert RelationKind.LABEL_RELEASE not in kinds


@pytest.mark.parametrize(
    ("route", "expected"),
    [
        ((403, b"<title>Just a moment...</title>"), [ErrorKind.BLOCKED]),
        ((404, b"gone"), []),
        ((500, b"oops"), [ErrorKind.FAILED]),
    ],
)
@pytest.mark.asyncio
async def test_review_page_failures_keep_the_api_facts(
    route: Route,
    expected: list[ErrorKind],
) -> None:
    adapter = make(routes(**{PAGE: route}))

    partial = await adapter.lookup(ALBUM, with_ids(ALBUM, discogs_master="1"))

    assert partial.candidate is not None
    assert [e.kind for e in partial.errors] == expected
    assert all(e.reason.startswith("reviews:") for e in partial.errors)


@pytest.mark.asyncio
async def test_missing_escalation_browser_costs_only_the_reviews() -> None:
    def unavailable(_: HttpSettings, __: str | None) -> Fetcher:
        raise ConfigurationError("Chromium for Playwright is not installed")

    table = routes(**{PAGE: (403, b"<title>Just a moment...</title>")})
    adapter = make(table, escalation=["browser"])
    adapter.resources.escalations = {
        Escalation.IMPERSONATE: unavailable,
        Escalation.BROWSER: unavailable,
    }
    adapter.resources.installed = lambda _: True

    partial = await adapter.lookup(ALBUM, with_ids(ALBUM, discogs_master="1"))

    assert partial.candidate is not None
    assert [e.kind for e in partial.errors] == [ErrorKind.BLOCKED]
    assert "Chromium" in partial.errors[0].reason


@pytest.mark.parametrize(
    ("discogs", "rate"),
    [({}, ANONYMOUS_RATE), ({"token": "t"}, 1.0), ({"rate": 2.0}, 2.0)],
)
def test_rate_without_a_token(discogs: dict[str, object], rate: float) -> None:
    adapter = DiscogsAdapter(SourcesConfig.model_validate({"discogs": discogs}), HttpResources())

    assert adapter.client._config.rate("discogs") == rate


def test_user_agent_setting_applies_to_both_clients() -> None:
    config = SourcesConfig.model_validate(
        {"discogs": {"user_agent": "Mine/1.0", "token": SecretStr("t")}},
    )
    adapter = DiscogsAdapter(config, HttpResources())

    assert adapter.client.spec.headers["user-agent"] == "Mine/1.0"
    assert adapter.page_client.spec.headers == {"user-agent": "Mine/1.0"}
