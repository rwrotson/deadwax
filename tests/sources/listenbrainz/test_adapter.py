import json

import httpx
import pytest

from deadwax.core import (
    EntityKind,
    ExternalId,
    Identity,
    IdKind,
    LookupContext,
    MetricKind,
    NotFoundError,
    Provenance,
    RelationKind,
    Scope,
    TextKind,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.listenbrainz import ListenBrainzAdapter
from deadwax.sources.listenbrainz.parse import published

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
    "/ws/1/review/": {
        "reviews": [
            REVIEW,
            {"id": "r2", "text": "Republished.", "source": "BBC"},
            {"id": "r3", "text": "  "},
        ],
    },
}


def make(seen: list[httpx.Request] | None = None) -> ListenBrainzAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, content=json.dumps(ROUTES[request.url.path]).encode())

    config = SourcesConfig.model_validate(
        {"listenbrainz": {"rate": 1000}, "http": {"retries": 0, "escalation": "none"}},
    )
    return ListenBrainzAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


def context(kind: EntityKind, *ids: tuple[IdKind, str]) -> LookupContext:
    query = parse_query("Band - Song", kind)
    sources = [Provenance(source="musicbrainz")]
    identity = Identity(
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
    assert [s[2:] for s in similar] == [("Next", "Other"), ("Later", None), ("Kin", None)]
    assert {s[0] for s in similar} == {RelationKind.SIMILAR}
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
