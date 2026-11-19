import pytest
from pydantic import ValidationError

from deadwax.core import (
    Capability,
    EntityKind,
    EntityType,
    RelationKind,
    RelationLimit,
    Request,
    text_query,
)

TRACK = text_query("Radiohead - Reckoner", EntityKind.TRACK)


def test_request_without_facets_wants_everything() -> None:
    request = Request(query=TRACK)

    assert all(request.wants(facet) for facet in Capability)


def test_request_wants_only_its_facets() -> None:
    request = Request(query=TRACK, facets=frozenset({Capability.TAGS}))

    assert request.wants(Capability.TAGS)
    assert not request.wants(Capability.LINKS)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"tags_per_source": 3}, "tags_per_source needs the tags facet"),
        (
            {"relations": (RelationLimit(kind=RelationKind.SIMILAR, per_source=2),)},
            "relations need the relations facet",
        ),
    ],
)
def test_limits_need_their_facet(fields: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Request.model_validate({"query": TRACK, "facets": {Capability.LINKS}} | fields)


def test_empty_relation_limits_need_no_facet() -> None:
    request = Request(query=TRACK, facets=frozenset({Capability.LINKS}), relations=())

    assert request.relations == ()


@pytest.mark.parametrize(
    ("target", "kind", "entity", "covered"),
    [
        (None, RelationKind.SIMILAR, EntityType.ARTIST, True),
        (EntityType.RECORDING, RelationKind.SIMILAR, EntityType.RECORDING, True),
        (EntityType.RECORDING, RelationKind.SIMILAR, EntityType.ARTIST, False),
        (None, RelationKind.MEMBER, EntityType.ARTIST, False),
    ],
)
def test_relation_limit_covers_its_kind_and_target(
    target: EntityType | None,
    kind: RelationKind,
    entity: EntityType,
    covered: bool,
) -> None:
    limit = RelationLimit(kind=RelationKind.SIMILAR, target=target, per_source=1)

    assert limit.covers(kind, entity) is covered


def test_relation_limit_needs_a_positive_cap() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        RelationLimit(kind=RelationKind.SIMILAR, per_source=0)
