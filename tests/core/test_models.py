from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from deadwax.core import (
    ArtistCandidate,
    ArtistIdentity,
    ArtistType,
    Candidate,
    Dossier,
    EntityKind,
    Identity,
    LabelCandidate,
    LabelIdentity,
    Partial,
    Provenance,
    Query,
    RecordCandidate,
    RecordIdentity,
    Relation,
    Scope,
    Sourced,
    Tag,
    UnresolvedQuery,
    text_query,
)


def test_dossier_round_trips_through_json() -> None:
    dossier = Dossier(
        query=text_query("Burial - Archangel", EntityKind.TRACK),
        identity=RecordIdentity(kind=EntityKind.TRACK),
        tags=[Tag(name="dubstep", scope=Scope.RECORDING, sources=[Provenance(source="lastfm")])],
        generated_at=datetime(2026, 11, 12, tzinfo=UTC),
    )

    assert Dossier.model_validate_json(dossier.model_dump_json()) == dossier


def test_relation_without_serialized_observations_defaults_to_empty() -> None:
    relation = Relation.model_validate_json(
        '{"kind":"similar","target":{"type":"recording","name":"Other"},'
        '"scope":"recording","sources":[{"source":"lastfm"}]}',
    )

    assert relation.similarity_observations == []


def test_dossier_requires_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        Dossier(
            query=text_query("A - B", EntityKind.TRACK),
            identity=RecordIdentity(),
            generated_at=datetime(2026, 11, 12),  # noqa: DTZ001 - the naive value is the point.
        )


def test_tag_weight_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Tag(name="x", scope=Scope.RECORDING, weight=3, sources=[])


def test_models_are_frozen() -> None:
    provenance = Provenance(source="discogs")

    with pytest.raises(ValidationError):
        provenance.source = "other"  # type: ignore[misc]


def test_json_schema_is_available() -> None:
    schema = Dossier.model_json_schema()

    assert {"query", "identity", "tags", "credits", "texts", "relations", "links", "errors"} <= set(
        schema["properties"],
    )


@pytest.mark.parametrize(
    ("query", "identity", "candidate"),
    [
        (
            text_query("Aphex Twin", EntityKind.ARTIST),
            ArtistIdentity(
                name=Sourced(value="Aphex Twin", sources=[Provenance(source="musicbrainz")]),
                type=Sourced(value=ArtistType.PERSON, sources=[Provenance(source="musicbrainz")]),
            ),
            ArtistCandidate(name="Aphex Twin", type=ArtistType.PERSON),
        ),
        (
            text_query("Warp", EntityKind.LABEL),
            LabelIdentity(country=Sourced(value="GB", sources=[Provenance(source="discogs")])),
            LabelCandidate(name="Warp", begin="1989"),
        ),
        (
            UnresolvedQuery(url="https://example.org/x"),
            RecordIdentity(),
            RecordCandidate(artist="Burial", title="Archangel"),
        ),
    ],
)
def test_each_kind_round_trips_through_json(
    query: Query,
    identity: Identity,
    candidate: Candidate,
) -> None:
    dossier = Dossier(
        query=query,
        identity=identity,
        generated_at=datetime(2026, 11, 12, tzinfo=UTC),
    )
    partial = Partial(source="x", candidate=candidate)

    restored = Dossier.model_validate_json(dossier.model_dump_json())

    assert restored == dossier
    assert type(restored.query) is type(query)
    assert type(restored.identity) is type(identity)
    assert type(Partial.model_validate_json(partial.model_dump_json()).candidate) is type(candidate)


def test_a_record_identity_or_candidate_is_a_track_or_album() -> None:
    with pytest.raises(ValidationError, match="not a track or album"):
        RecordIdentity(kind=EntityKind.ARTIST)
    with pytest.raises(ValidationError, match="not a track or album"):
        RecordCandidate(kind=EntityKind.LABEL, artist="A", title="B")


def test_a_name_identity_is_found_by_its_name() -> None:
    name = Sourced(value="Warp", sources=[Provenance(source="discogs")])

    assert LabelIdentity(name=name).found
    assert not LabelIdentity().found
    assert not ArtistIdentity().found
