from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from deadwax import (
    ArtistIdentity,
    ArtistQuery,
    ArtistType,
    Capability,
    Dossier,
    EntityKind,
    ErrorKind,
    IdKind,
    LabelIdentity,
    LinkTarget,
    LookupConfig,
    MetricKind,
    Query,
    RelationKind,
    Request,
    Scope,
    lookup,
    parse_query,
)

Replay = Callable[..., httpx.MockTransport]

APHEX_TWIN = "f22942a1-6f70-4f48-866e-238cb2308fbd"
WARP = "46f0f4cd-8aab-4b33-b698-f459faf64190"
LASTFM_APHEX = "https://www.last.fm/music/Aphex+Twin"


async def replayed(query: Query, scenario: str, replay: Replay, config: LookupConfig) -> Dossier:
    seen: list[str] = []
    dossier = await lookup(query, config, transport=replay(scenario, seen))
    assert seen
    assert [e for e in dossier.errors if e.kind is ErrorKind.FAILED] == []
    return dossier


def ids(dossier: Dossier) -> dict[IdKind, str]:
    return {external.kind: external.value for external in dossier.identity.external_ids}


def errors(dossier: Dossier) -> dict[str, ErrorKind]:
    return {error.source: error.kind for error in dossier.errors}


def relation_kinds(dossier: Dossier) -> set[RelationKind]:
    return {relation.kind for relation in dossier.relations}


@pytest.mark.parametrize(
    ("query", "scenario", "expected"),
    [
        (
            parse_query("Aphex Twin", EntityKind.ARTIST),
            "discogs_artist_search",
            {IdKind.DISCOGS_ARTIST: "45"},
        ),
        (
            parse_query("Warp", EntityKind.LABEL),
            "discogs_label_search",
            {IdKind.DISCOGS_LABEL: "1038614"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_discogs_search(
    query: Query,
    scenario: str,
    expected: dict[IdKind, str],
    replay: Replay,
    config: LookupConfig,
) -> None:
    discogs = config.sources.discogs.model_copy(update={"token": SecretStr("test-token")})
    config = config.model_copy(
        update={"sources": config.sources.model_copy(update={"discogs": discogs})},
    )
    seen: list[str] = []
    dossier = await lookup(
        query,
        config,
        include=("discogs",),
        transport=replay(scenario, seen),
    )
    assert not dossier.errors
    assert ids(dossier) == expected
    assert "/database/search?" in seen[0]


@pytest.mark.parametrize(
    ("url", "scenario", "expected"),
    [
        ("artist/45-Aphex-Twin", "aphex_twin", {IdKind.DISCOGS_ARTIST: "45"}),
        ("label/23528-Warp-Records", "warp", {IdKind.DISCOGS_LABEL: "23528"}),
    ],
)
@pytest.mark.asyncio
async def test_discogs_url(
    url: str,
    scenario: str,
    expected: dict[IdKind, str],
    replay: Replay,
    config: LookupConfig,
) -> None:
    dossier = await lookup(
        parse_query(f"https://www.discogs.com/{url}"),
        config,
        include=("discogs",),
        transport=replay(scenario),
    )
    assert not dossier.errors
    assert ids(dossier) == expected


@pytest.mark.asyncio
async def test_discogs_profile_blocked(config: LookupConfig) -> None:
    dossier = await lookup(
        parse_query("https://www.discogs.com/artist/45"),
        config,
        include=("discogs",),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(403, content=b"<title>Just a moment...</title>"),
        ),
    )
    assert errors(dossier) == {"discogs": ErrorKind.BLOCKED}


@pytest.mark.asyncio
async def test_artist_by_name(replay: Replay, config: LookupConfig) -> None:
    dossier = await replayed(
        parse_query("Aphex Twin", EntityKind.ARTIST),
        "aphex_twin",
        replay,
        config,
    )

    identity = dossier.identity
    assert isinstance(identity, ArtistIdentity)
    assert identity.name is not None
    assert identity.name.value == "Aphex Twin"
    assert identity.type is not None
    assert identity.type.value is ArtistType.PERSON
    assert ids(dossier)[IdKind.MUSICBRAINZ_ARTIST] == APHEX_TWIN
    assert {IdKind.DISCOGS_ARTIST, IdKind.WIKIDATA} <= ids(dossier).keys()
    assert {RelationKind.LABEL, RelationKind.RELEASE, RelationKind.ALIAS} <= relation_kinds(dossier)
    assert {
        link.target
        for link in dossier.links
        if any(source.source == "musicbrainz" for source in link.sources)
    } == {LinkTarget.ARTIST}
    assert "musicbrainz" not in errors(dossier)
    assert "discogs" not in errors(dossier)
    assert any(text.publication == "Discogs" for text in dossier.texts)


@pytest.mark.asyncio
async def test_artist_by_musicbrainz_url(replay: Replay, config: LookupConfig) -> None:
    query = parse_query(f"https://musicbrainz.org/artist/{APHEX_TWIN}")

    dossier = await replayed(query, "musicbrainz_artist_url", replay, config)

    assert isinstance(dossier.identity, ArtistIdentity)
    assert ids(dossier)[IdKind.MUSICBRAINZ_ARTIST] == APHEX_TWIN
    assert {metric.kind for metric in dossier.metrics} == {MetricKind.LISTENERS, MetricKind.LISTENS}


@pytest.mark.asyncio
async def test_label_by_name(replay: Replay, config: LookupConfig) -> None:
    dossier = await replayed(parse_query("Warp", EntityKind.LABEL), "warp", replay, config)

    identity = dossier.identity
    assert isinstance(identity, LabelIdentity)
    assert identity.country is not None
    assert identity.country.value == "GB"
    assert ids(dossier)[IdKind.MUSICBRAINZ_LABEL] == WARP
    assert {RelationKind.SUBLABEL, RelationKind.ASSOCIATED} <= relation_kinds(dossier)
    assert RelationKind.LABEL_RELEASE in relation_kinds(dossier)
    assert "discogs" not in errors(dossier)


@pytest.mark.parametrize(
    ("query", "scenario", "sources"),
    [
        (ArtistQuery(name="Aphex Twin"), "lastfm_artist_search", ("lastfm",)),
        (parse_query(LASTFM_APHEX), "lastfm_artist_url", ("lastfm",)),
        (
            ArtistQuery(name="Aphex Twin"),
            "aphex_twin",
            ("musicbrainz", "lastfm"),
        ),
    ],
)
@pytest.mark.asyncio
async def test_lastfm_artist(
    query: Query,
    scenario: str,
    sources: tuple[str, ...],
    replay: Replay,
    config: LookupConfig,
) -> None:
    seen: list[str] = []
    dossier = await lookup(query, config, include=sources, transport=replay(scenario, seen))

    assert not dossier.errors
    assert isinstance(dossier.identity, ArtistIdentity)
    assert dossier.identity.name is not None
    assert dossier.identity.name.value == "Aphex Twin"
    assert ids(dossier)[IdKind.MUSICBRAINZ_ARTIST] == APHEX_TWIN
    [info] = [request for request in seen if "method=artist.getInfo" in request]
    lookup_param = f"mbid={APHEX_TWIN}" if "musicbrainz" in sources else "autocorrect=1"
    assert lookup_param in info
    assert {metric.kind for metric in dossier.metrics} == {MetricKind.LISTENERS, MetricKind.LISTENS}
    for facts in (dossier.texts, dossier.tags, dossier.relations, dossier.metrics):
        from_lastfm = [fact for fact in facts if any(s.source == "lastfm" for s in fact.sources)]
        assert from_lastfm
        assert all(
            source.url == LASTFM_APHEX
            for fact in from_lastfm
            for source in fact.sources
            if source.source == "lastfm"
        )
    assert all(metric.scope is Scope.ARTIST and metric.value > 0 for metric in dossier.metrics)


@pytest.mark.parametrize("matches", [True, False])
@pytest.mark.asyncio
async def test_lastfm_artist_metrics_only(matches: bool, config: LookupConfig) -> None:
    query = ArtistQuery(name="Band", ids={IdKind.MUSICBRAINZ_ARTIST: APHEX_TWIN})
    request = Request(query=query, facets=frozenset({Capability.METRICS}))
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["mbid"] == APHEX_TWIN
        seen.append(request.url.params["method"])
        return httpx.Response(
            200,
            json={
                "artist": {
                    "name": "Band",
                    "url": "https://www.last.fm/music/Band",
                    "mbid": APHEX_TWIN if matches else WARP,
                    "stats": {"listeners": "0"},
                    "bio": {"summary": "About the band."},
                },
            },
        )

    dossier = await lookup(
        request,
        config,
        include=("lastfm",),
        transport=httpx.MockTransport(respond),
    )

    assert seen == ["artist.getInfo"]
    assert not dossier.texts
    assert not dossier.tags
    assert not dossier.relations
    if matches:
        assert not dossier.errors
        assert [(metric.kind, metric.value) for metric in dossier.metrics] == [
            (MetricKind.LISTENERS, 0),
        ]
    else:
        assert errors(dossier) == {"lastfm": ErrorKind.NO_MATCH}
        assert not dossier.metrics


@pytest.mark.parametrize("key", [None, SecretStr("test-key")])
@pytest.mark.asyncio
async def test_lastfm_artist_unavailable(key: SecretStr | None, config: LookupConfig) -> None:
    lastfm = config.sources.lastfm.model_copy(update={"api_key": key})
    config = config.model_copy(
        update={"sources": config.sources.model_copy(update={"lastfm": lastfm})},
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert key is not None
        assert request.url.params["artist"] == "AC/DC"
        return httpx.Response(200, json={"error": 6, "message": "Artist not found"})

    dossier = await lookup(
        parse_query("https://last.fm/music/AC%2FDC/"),
        config,
        include=("lastfm",),
        transport=httpx.MockTransport(respond),
    )

    expected = ErrorKind.SKIPPED if key is None else ErrorKind.NOT_FOUND
    assert errors(dossier) == {"lastfm": expected}
