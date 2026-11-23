import json

import httpx
import pytest

from deadwax.core import (
    Capability,
    EntityKind,
    EntityType,
    ExternalId,
    IdKind,
    LookupContext,
    MetricKind,
    NotFoundError,
    Provenance,
    RecordIdentity,
    RelationKind,
    Scope,
    SimilarityObservation,
    TextKind,
)
from deadwax.sources import LookupConfig, parse_query
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.listenbrainz import ListenBrainzAdapter
from deadwax.sources.adapters.listenbrainz.parse import published

RECORDING = "11111111-1111-1111-1111-111111111111"
GROUP = "22222222-2222-2222-2222-222222222222"
ARTIST = "33333333-3333-3333-3333-333333333333"
REVIEW = {
    "id": "r1",
    "text": "Dense and warm.\r\n\r\nGreat bass.",
    "rating": 4,
    "language": "en",
    "published_on": "Fri, 26 Sep 2014 16:31:32 GMT",
    "user": {"display_name": "listener"},
}
ROUTES: dict[str, object] = {
    "/1/popularity/recording": [{"total_listen_count": 120, "total_user_count": 0}],
    "/1/popularity/release-group": [{"total_listen_count": None, "total_user_count": 7}],
    "/similar-recordings/json": [
        {"recording_mbid": "r2", "recording_name": "Next", "artist_credit_name": "Other"},
        {"recording_mbid": "r3", "recording_name": "Later", "artist_credit_name": ""},
    ],
    "/similar-artists/json": [{"artist_mbid": "a2", "name": "Kin"}],
    f"/1/lb-radio/artist/{ARTIST}": {
        ARTIST: [{"recording_mbid": "own", "similar_artist_mbid": ARTIST}],
        "a2": [
            {"recording_mbid": "r5", "similar_artist_mbid": "a2", "similar_artist_name": "Kin"},
            {"recording_mbid": "r6", "similar_artist_mbid": "a2", "similar_artist_name": "Kin"},
        ],
        "a3": [{"recording_mbid": "r7", "similar_artist_mbid": "a3", "similar_artist_name": "Far"}],
    },
    "/1/metadata/recording/": {
        "r5": {"recording": {"name": "Radio One"}, "artist": {"name": "Kin & Cast"}},
        "r6": {"recording": {"name": "Radio Two"}},
        "r7": {"recording": {}},
    },
    "/ws/1/review/": {
        "reviews": [
            REVIEW,
            {"id": "r2", "text": "Republished.", "source": "BBC"},
            {"id": "r3", "text": "  "},
        ],
    },
}


def make(
    seen: list[httpx.Request] | None = None,
    routes: dict[str, object] | None = None,
    **settings: object,
) -> ListenBrainzAdapter:
    table = ROUTES | (routes or {})

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, content=json.dumps(table[request.url.path]).encode())

    config = LookupConfig.model_validate(
        {
            "sources": {"listenbrainz": {"rate": 1000, **settings}},
            "http": {"retries": 0, "escalation": []},
        },
    )
    return ListenBrainzAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


def context(kind: EntityKind, *ids: tuple[IdKind, str]) -> LookupContext:
    query = parse_query("Band - Song", kind)
    sources = [Provenance(source="musicbrainz")]
    identity = RecordIdentity(
        kind=kind,
        external_ids=[ExternalId(kind=k, value=v, sources=sources) for k, v in ids],
    )
    return LookupContext(query=query, identity=identity)


@pytest.mark.asyncio
async def test_track() -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen)
    found = context(
        EntityKind.TRACK,
        (IdKind.MUSICBRAINZ_RECORDING, RECORDING),
        (IdKind.MUSICBRAINZ_RELEASE_GROUP, GROUP),
        (IdKind.MUSICBRAINZ_ARTIST, ARTIST),
    )

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    assert partial.candidate is None
    assert [(m.kind, m.value, m.scope) for m in partial.metrics] == [
        (MetricKind.LISTENS, 120, Scope.RECORDING),
    ]
    assert partial.metrics[0].sources[0].url == f"https://listenbrainz.org/track/{RECORDING}/"
    assert json.loads(seen[0].content) == {"recording_mbids": [RECORDING]}
    similar = [(r.kind, r.target.type, r.target.name, r.target.artist) for r in partial.relations]
    assert [s[2:] for s in similar] == [
        ("Next", "Other"),
        ("Later", None),
        ("Kin", None),
        ("Radio One", "Kin & Cast"),
        ("Radio Two", "Kin"),
    ]
    assert {s[0] for s in similar[:3]} == {RelationKind.SIMILAR}
    assert {s[0] for s in similar[3:]} == {RelationKind.SIMILAR_ARTIST_RECORDING}
    assert partial.relations[0].target.ids == {IdKind.MUSICBRAINZ_RECORDING: "r2"}
    review = partial.texts[0]
    assert (review.kind, review.body, review.author, review.date) == (
        TextKind.USER,
        "Dense and warm.\n\nGreat bass.",
        "listener",
        "2014-09-26",
    )
    assert review.rating is not None
    assert (review.rating.value, review.rating.scale) == (4, 5)
    assert review.sources[0].url == "https://critiquebrainz.org/review/r1"
    assert (partial.texts[1].kind, partial.texts[1].publication) == (TextKind.REVIEW, "BBC")
    assert [t.scope for t in partial.texts] == [Scope.RECORDING] * 2 + [Scope.RELEASE_GROUP] * 2


@pytest.mark.asyncio
async def test_album() -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen)
    found = context(EntityKind.ALBUM, (IdKind.MUSICBRAINZ_RELEASE_GROUP, GROUP))

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    assert [(m.kind, m.value, m.scope) for m in partial.metrics] == [
        (MetricKind.LISTENERS, 7, Scope.RELEASE_GROUP),
    ]
    assert json.loads(seen[0].content) == {"release_group_mbids": [GROUP]}
    assert partial.relations == []
    assert {t.scope for t in partial.texts} == {Scope.RELEASE_GROUP}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "missing"),
    [(EntityKind.TRACK, "recording"), (EntityKind.ALBUM, "release group")],
)
async def test_needs_an_mbid(kind: EntityKind, missing: str) -> None:
    adapter = make()
    found = context(kind, (IdKind.MUSICBRAINZ_ARTIST, ARTIST))

    with pytest.raises(NotFoundError, match=missing):
        await adapter.lookup(found.query, found)


def test_published_dates() -> None:
    assert published(None) is None
    assert published("not a date") is None
    assert published("Fri, 25 Jan 2008 00:00:00 GMT") == "2008-01-25"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "facet", "paths"),
    [
        (EntityKind.TRACK, Capability.METRICS, {"/1/popularity/recording"}),
        (
            EntityKind.TRACK,
            Capability.RELATIONS,
            {
                "/similar-recordings/json",
                "/similar-artists/json",
                f"/1/lb-radio/artist/{ARTIST}",
                "/1/metadata/recording/",
            },
        ),
        (EntityKind.TRACK, Capability.TEXTS, {"/ws/1/review/"}),
        (EntityKind.ALBUM, Capability.METRICS, {"/1/popularity/release-group"}),
        (EntityKind.ALBUM, Capability.RELATIONS, {"/similar-artists/json"}),
        (EntityKind.ALBUM, Capability.TEXTS, {"/ws/1/review/"}),
    ],
)
async def test_asks_only_for_wanted_facets(
    kind: EntityKind,
    facet: Capability,
    paths: set[str],
) -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen)
    found = context(
        kind,
        (IdKind.MUSICBRAINZ_RECORDING, RECORDING),
        (IdKind.MUSICBRAINZ_RELEASE_GROUP, GROUP),
        (IdKind.MUSICBRAINZ_ARTIST, ARTIST),
    ).model_copy(update={"facets": frozenset({facet})})

    await adapter.lookup(found.query, found)
    await adapter.aclose()

    assert {request.url.path for request in seen} == paths


def track_context(*ids: tuple[IdKind, str]) -> LookupContext:
    found = context(EntityKind.TRACK, (IdKind.MUSICBRAINZ_RECORDING, RECORDING), *ids)
    return found.model_copy(update={"facets": frozenset({Capability.RELATIONS})})


@pytest.mark.asyncio
async def test_similarity_observations_keep_endpoint_scores_and_ranks() -> None:
    scores = [0.12345678912345, 0.0, None]
    adapter = make(
        routes={
            "/similar-recordings/json": [
                {"recording_mbid": f"r{index}", "recording_name": f"Track {index}", "score": score}
                for index, score in enumerate(scores)
            ],
            "/similar-artists/json": [
                {"artist_mbid": f"a{index}", "name": f"Artist {index}", "score": score}
                for index, score in enumerate(scores)
            ],
        },
    )
    found = track_context((IdKind.MUSICBRAINZ_ARTIST, ARTIST))

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    for kind, prefix in ((EntityType.RECORDING, "Track"), (EntityType.ARTIST, "Artist")):
        similar = [
            relation
            for relation in partial.relations
            if relation.kind is RelationKind.SIMILAR and relation.target.type is kind
        ]
        assert [relation.target.name for relation in similar] == [
            f"{prefix} 0",
            f"{prefix} 1",
            f"{prefix} 2",
        ]
        for rank, (relation, score) in enumerate(zip(similar, scores, strict=True), start=1):
            assert relation.similarity_observations == [
                SimilarityObservation(provenance=relation.sources[0], score=score, rank=rank),
            ]
            assert relation.sources[0].source == "listenbrainz"


@pytest.mark.asyncio
async def test_radio_recordings_of_similar_artists() -> None:
    seen: list[httpx.Request] = []
    adapter = make(
        seen,
        routes={
            "/1/metadata/recording/": {
                "r5": {"recording": {"name": "First"}},
                "r6": {"recording": {}},
                "r7": {"recording": {"name": "Third"}},
            },
        },
        radio_artists=3,
        radio_per_artist=1,
    )
    found = track_context((IdKind.MUSICBRAINZ_ARTIST, ARTIST))

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    radio, names = (r for r in seen if r.url.path.startswith("/1/"))
    assert dict(radio.url.params) == {
        "mode": "easy",
        "max_similar_artists": "3",
        "max_recordings_per_artist": "1",
        "pop_begin": "0",
        "pop_end": "100",
    }
    assert dict(names.url.params) == {"recording_mbids": "r5,r6,r7", "inc": "artist"}
    first, third = [r for r in partial.relations if r.kind is RelationKind.SIMILAR_ARTIST_RECORDING]
    assert [r.target.name for r in (first, third)] == ["First", "Third"]
    for relation, rank in ((first, 2), (third, 4)):
        assert relation.similarity_observations == [
            SimilarityObservation(provenance=relation.sources[0], rank=rank),
        ]
    assert (first.target.type, first.scope) == (EntityType.RECORDING, Scope.ARTIST)
    assert first.target.url == "https://musicbrainz.org/recording/r5"
    assert first.target.ids == {IdKind.MUSICBRAINZ_RECORDING: "r5"}
    assert first.sources[0].url == f"https://listenbrainz.org/artist/{ARTIST}/"


@pytest.mark.asyncio
async def test_radio_resolves_at_most_forty_recordings() -> None:
    seen: list[httpx.Request] = []
    items = [{"recording_mbid": f"m{n}", "similar_artist_mbid": "a2"} for n in range(45)]
    routes: dict[str, object] = {f"/1/lb-radio/artist/{ARTIST}": {"a2": items}}
    adapter = make(seen, routes)
    found = track_context((IdKind.MUSICBRAINZ_ARTIST, ARTIST))

    await adapter.lookup(found.query, found)
    await adapter.aclose()

    names = next(r for r in seen if r.url.path == "/1/metadata/recording/")
    assert names.url.params["recording_mbids"].split(",") == [f"m{n}" for n in range(40)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "radio",
    [{}, {ARTIST: [{"recording_mbid": "own", "similar_artist_mbid": ARTIST}]}],
)
async def test_radio_without_other_artists_resolves_nothing(radio: dict[str, object]) -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen, {f"/1/lb-radio/artist/{ARTIST}": radio})
    found = track_context((IdKind.MUSICBRAINZ_ARTIST, ARTIST))

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    assert "/1/metadata/recording/" not in {r.url.path for r in seen}
    assert RelationKind.SIMILAR_ARTIST_RECORDING not in {r.kind for r in partial.relations}


@pytest.mark.asyncio
async def test_radio_needs_an_artist_mbid() -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen)
    found = track_context()

    partial = await adapter.lookup(found.query, found)
    await adapter.aclose()

    assert {r.url.path for r in seen} == {"/similar-recordings/json"}
    assert {r.kind for r in partial.relations} == {RelationKind.SIMILAR}
