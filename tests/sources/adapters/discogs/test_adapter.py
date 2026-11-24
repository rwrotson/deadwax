import json
from collections.abc import Callable, Mapping

import httpx
import pytest
from pydantic import SecretStr

from deadwax.core import (
    ArtistCandidate,
    Capability,
    EntityKind,
    ErrorKind,
    ExternalId,
    IdKind,
    LabelCandidate,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Provenance,
    Query,
    RecordCandidate,
    RecordIdentity,
    RelationKind,
    Scope,
    SourceState,
    TextKind,
    UnresolvedQuery,
)
from deadwax.sources import LookupConfig, parse_query
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.discogs import DiscogsAdapter
from deadwax.sources.adapters.discogs.adapter import ANONYMOUS_RATE, DEFAULT_USER_AGENT

API = "https://api.discogs.com"
TRACKS = [{"position": "A1", "title": "Song"}, {"position": "A2", "title": "Other"}]
ARTISTS = [{"id": 3, "name": "Band"}]
MASTER = {"id": 1, "title": "Record", "main_release": 10, "artists": ARTISTS,
          "genres": ["Electronic"], "styles": ["Ambient"], "notes": "Master note"}  # fmt: skip
RELEASE = {"id": 10, "title": "Record", "master_id": 1, "released": "2020-02-03",
           "artists": ARTISTS, "labels": [{"id": 5, "name": "Label", "catno": "L1"}],
           "tracklist": TRACKS, "notes": "Release note"}  # fmt: skip
type Route = tuple[int, object]


def routes(**changes: Route) -> dict[str, Route]:
    base: dict[str, Route] = {
        f"{API}/masters/1": (200, MASTER),
        f"{API}/releases/10": (200, RELEASE),
        f"{API}/masters/1/versions": (200, {"versions": [{"id": 11, "title": "Record"}]}),
        f"{API}/artists/3": (200, {"id": 3, "name": "Band", "members": [{"id": 4, "name": "M"}]}),
        f"{API}/labels/5/releases": (200, {"releases": [{"id": 12, "title": "Next"}]}),
    }
    return base | {key.replace("__", "/"): value for key, value in changes.items()}


def make(
    table: Mapping[str, Route],
    *,
    token: str | None = None,
    seen: list[httpx.Request] | None = None,
    search: Callable[[httpx.Request], Route] | None = None,
) -> DiscogsAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.discogs.com"
        if seen is not None:
            seen.append(request)
        url = str(request.url.copy_with(query=None))
        if url == f"{API}/database/search" and search is not None:
            status, body = search(request)
        else:
            status, body = table.get(url, (404, {"message": "not found"}))
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return httpx.Response(status, content=content)

    config = LookupConfig.model_validate(
        {
            "sources": {"discogs": {"rate": 1000, "token": token}},
            "http": {"retries": 0, "escalation": []},
        },
    )
    return DiscogsAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


def with_ids(query: Query, **ids: str) -> LookupContext:
    external = [
        ExternalId(kind=IdKind(kind), value=value, sources=[Provenance(source="musicbrainz")])
        for kind, value in ids.items()
    ]
    return LookupContext(query=query, identity=RecordIdentity(external_ids=external))


ALBUM = parse_query("Band - Record", EntityKind.ALBUM)
TRACK = parse_query("Band - Song", EntityKind.TRACK)


@pytest.mark.asyncio
async def test_artist_url_reads_profile_and_main_masters() -> None:
    query = parse_query("https://www.discogs.com/artist/3-Band")
    master = {"id": 20, "title": "Record", "type": "master", "role": "Main"}
    seen: list[httpx.Request] = []
    adapter = make(
        {
            f"{API}/artists/3": (
                200,
                {
                    "id": 3,
                    "name": "Band (2)",
                    "realname": " Real Name ",
                    "profile": " From Discogs.\r\n Biography.",
                    "aliases": [{"id": 4, "name": "Alias"}, {"id": 5, "name": "Unknown"}],
                    "namevariations": ["Alias", "Band", "The Band", "unknown", ""],
                    "members": [{"id": 6, "name": "Member", "active": False}],
                    "groups": [{"id": 7, "name": "Group"}],
                    "urls": [
                        "https://band.bandcamp.com",
                        "https://www.band.example",
                        "https://band.bandcamp.com",
                        "ftp://band.example",
                        "https://[bad",
                    ],
                },
            ),
            f"{API}/artists/3/releases": (
                200,
                {
                    "releases": [
                        {**master, "type": "release"},
                        {**master, "role": "Appearance"},
                        master,
                        master,
                        *({**master, "id": i} for i in range(21, 36)),
                    ],
                },
            ),
        },
        seen=seen,
    )
    assert adapter.resolves(query)
    partial = await adapter.lookup(query, LookupContext(query=query))
    assert isinstance(partial.candidate, ArtistCandidate)
    assert partial.candidate.name == "Band"
    assert partial.candidate.disambiguation == "Real Name"
    assert partial.candidate.ids == {IdKind.DISCOGS_ARTIST: "3"}
    [profile] = partial.texts
    assert (profile.title, profile.kind, profile.scope) == ("Profile", TextKind.WIKI, Scope.ARTIST)
    assert profile.body == "From Discogs.\n Biography."
    assert [r.target.name for r in partial.relations if r.kind is RelationKind.ALIAS] == [
        "Alias",
        "The Band",
    ]
    assert any(r.kind is RelationKind.MEMBER and r.note == "former" for r in partial.relations)
    assert any(
        r.kind is RelationKind.PROJECT and r.target.name == "Group" for r in partial.relations
    )
    masters = [r for r in partial.relations if r.kind is RelationKind.RELEASE]
    assert [r.target.ids[IdKind.DISCOGS_MASTER] for r in masters] == [str(i) for i in range(20, 32)]
    assert [(link.service, link.target) for link in partial.links] == [
        ("bandcamp", LinkTarget.ARTIST),
        ("band.example", LinkTarget.ARTIST),
    ]
    for fact in [*partial.relations, *partial.texts, *partial.links]:
        assert fact.sources == [Provenance(source="discogs", url=partial.candidate.url)]
    assert all("authorization" not in request.headers for request in seen)
    assert seen[-1].url.params["sort"] == "year"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_label_url_reads_profile_hierarchy_and_catalog() -> None:
    query = parse_query("https://www.discogs.com/label/5-Label")
    adapter = make(
        {
            f"{API}/labels/5": (
                200,
                {
                    "id": 5,
                    "name": "Label (2)",
                    "profile": " A label ",
                    "parent_label": {"id": 6, "name": "Parent (2)"},
                    "sublabels": [{"id": 7, "name": "Imprint"}],
                    "urls": ["https://label.bandcamp.com"],
                },
            ),
            f"{API}/labels/5/releases": (
                200,
                {
                    "releases": [{"id": 10, "title": "Record"}, {"id": 11, "title": "Record"}],
                },
            ),
        },
    )
    assert adapter.resolves(query)
    partial = await adapter.lookup(query, LookupContext(query=query))
    assert isinstance(partial.candidate, LabelCandidate)
    assert partial.candidate.name == "Label"
    assert partial.candidate.ids == {IdKind.DISCOGS_LABEL: "5"}
    assert partial.texts[0].scope is Scope.LABEL
    assert partial.links[0].target is LinkTarget.LABEL
    assert [(r.kind, r.target.name, r.target.ids) for r in partial.relations] == [
        (RelationKind.PARENT_LABEL, "Parent", {IdKind.DISCOGS_LABEL: "6"}),
        (RelationKind.SUBLABEL, "Imprint", {IdKind.DISCOGS_LABEL: "7"}),
        (RelationKind.LABEL_RELEASE, "Record", {IdKind.DISCOGS_RELEASE: "10"}),
    ]
    await adapter.aclose()


@pytest.mark.parametrize(
    ("kind", "path"),
    [(EntityKind.ARTIST, "artists"), (EntityKind.LABEL, "labels")],
)
@pytest.mark.asyncio
async def test_name_search_ranks_results_and_skips_unrequested_discography(
    kind: EntityKind,
    path: str,
) -> None:
    query = parse_query("The Label", kind)
    seen: list[httpx.Request] = []

    def search(request: httpx.Request) -> Route:
        assert dict(request.url.params) == {"q": "The Label", "type": kind.value, "per_page": "25"}
        assert request.headers["authorization"] == "Discogs token=test"
        return 200, {
            "results": [
                {"id": 1, "type": "master", "title": "The Label"},
                {"id": 2, "type": kind.value, "title": "Other"},
                {"id": 3, "type": kind.value, "title": "The Label (2)"},
                {"id": 4, "type": kind.value, "title": "The Label"},
            ],
        }

    adapter = make(
        {f"{API}/{path}/3": (200, {"id": 3, "name": "The Label (2)"})},
        token="test",
        search=search,
        seen=seen,
    )
    partial = await adapter.lookup(
        query,
        LookupContext(query=query, facets=frozenset({Capability.IDENTITY})),
    )
    assert isinstance(partial.candidate, ArtistCandidate | LabelCandidate)
    assert partial.candidate.name == "The Label"
    assert partial.candidate.kind is kind
    assert not partial.relations
    assert [request.url.path for request in seen] == ["/database/search", f"/{path}/3"]
    await adapter.aclose()


@pytest.mark.asyncio
async def test_artist_and_label_search_without_a_token_are_skipped() -> None:
    seen: list[httpx.Request] = []
    adapter = make({}, seen=seen)
    for kind in (EntityKind.ARTIST, EntityKind.LABEL):
        query = parse_query("Missing", kind)
        partial = await adapter.lookup(query, LookupContext(query=query))
        assert [error.kind for error in partial.errors] == [ErrorKind.SKIPPED]
    assert not seen
    await adapter.aclose()


@pytest.mark.asyncio
async def test_name_search_empty_and_missing_profile() -> None:
    adapter = make({}, token="test", search=lambda _: (200, {"results": []}))
    for query in (
        parse_query("Missing", EntityKind.ARTIST),
        parse_query("https://www.discogs.com/label/5-Label"),
        parse_query("https://open.spotify.com/artist/abc"),
    ):
        with pytest.raises(NotFoundError):
            await adapter.lookup(query, LookupContext(query=query))
    await adapter.aclose()


@pytest.mark.asyncio
async def test_album_by_master_id_from_an_earlier_pass() -> None:
    seen: list[httpx.Request] = []
    adapter = make(routes(), seen=seen)

    partial = await adapter.lookup(ALBUM, with_ids(ALBUM, discogs_master="1"))

    assert partial.candidate is not None
    assert partial.candidate.ids[IdKind.DISCOGS_RELEASE] == "10"
    assert [t.title for t in partial.texts] == ["Master notes", "Release notes"]
    kinds = {r.kind for r in partial.relations}
    assert {RelationKind.OTHER_VERSION, RelationKind.MEMBER, RelationKind.LABEL_RELEASE} <= kinds
    assert {r.headers["user-agent"] for r in seen} == {DEFAULT_USER_AGENT}
    assert all("authorization" not in r.headers for r in seen)
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
        (
            ErrorKind.SKIPPED,
            "search needs sources.discogs.token, and earlier sources found no Discogs ID",
        ),
    ]
    assert adapter.status().state is SourceState.READY
    assert adapter.status().detail == "no sources.discogs.token: no search"


@pytest.mark.asyncio
async def test_nothing_to_search_for() -> None:
    query = UnresolvedQuery(url="https://example.com/x")

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

    assert isinstance(partial.candidate, RecordCandidate)
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


def test_api_access_with_no_permitted_html_transports() -> None:
    config = LookupConfig.model_validate(
        {"http": {"escalation": []}, "sources": {"discogs": {"html_transports": ["browser"]}}},
    )
    adapter = DiscogsAdapter(config, HttpResources())

    assert adapter.status().ready
    access = adapter.access()
    assert access.api
    assert access.html_transports == []
    assert access.browser_headless is None
    assert not access.headed_fallback


@pytest.mark.parametrize(
    ("discogs", "rate"),
    [({}, ANONYMOUS_RATE), ({"token": "t"}, 1.0), ({"rate": 2.0}, 2.0)],
)
def test_rate_without_a_token(discogs: dict[str, object], rate: float) -> None:
    adapter = DiscogsAdapter(
        LookupConfig.model_validate({"sources": {"discogs": discogs}}),
        HttpResources(),
    )

    assert adapter.client.settings.rate == rate


def test_user_agent_setting_applies_to_the_api_client() -> None:
    config = LookupConfig.model_validate(
        {"sources": {"discogs": {"user_agent": "Mine/1.0", "token": SecretStr("t")}}},
    )
    adapter = DiscogsAdapter(config, HttpResources())

    assert adapter.client.spec.headers["user-agent"] == "Mine/1.0"
