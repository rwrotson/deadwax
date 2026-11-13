from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from deadwax.core import Dossier, EntityKind, Identity, Provenance, Scope, Tag, parse_query


def test_dossier_round_trips_through_json() -> None:
    dossier = Dossier(
        query=parse_query("Burial - Archangel", EntityKind.TRACK),
        identity=Identity(kind=EntityKind.TRACK),
        tags=[Tag(name="dubstep", scope=Scope.RECORDING, sources=[Provenance(source="lastfm")])],
        generated_at=datetime(2026, 11, 12, tzinfo=UTC),
    )

    assert Dossier.model_validate_json(dossier.model_dump_json()) == dossier


def test_dossier_requires_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        Dossier(
            query=parse_query("A - B", EntityKind.TRACK),
            identity=Identity(),
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
