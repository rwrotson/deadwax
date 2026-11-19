from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from deadwax.core.adapter import Capability
from deadwax.core.models import EntityType, RelationKind
from deadwax.core.query import Query


class RelationLimit(BaseModel):
    """Relation kind a request wants, with a cap per source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: RelationKind
    target: EntityType | None = Field(
        default=None,
        description="Type of the related entity; any type when unset",
    )
    per_source: int = Field(
        ge=1,
        description="Relations kept per source, kind, and target type, in merge order",
    )

    def covers(self, kind: RelationKind, target: EntityType) -> bool:
        """Whether a relation of this kind and target type is wanted."""
        return kind is self.kind and (self.target is None or target is self.target)


class Request(BaseModel):
    """Record to look up and the facts wanted about it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: Query
    facets: frozenset[Capability] | None = Field(
        default=None,
        description="Kinds of facts wanted; all when unset",
    )
    tags_per_source: int | None = Field(
        default=None,
        ge=1,
        description="Tags kept per source, in merge order; no cap when unset",
    )
    relations: tuple[RelationLimit, ...] | None = Field(
        default=None,
        description="Relation kinds wanted; every kind without a cap when unset",
    )

    @model_validator(mode="after")
    def _limits_need_facets(self) -> Self:
        if self.tags_per_source is not None and not self.wants(Capability.TAGS):
            raise ValueError("tags_per_source needs the tags facet")
        if self.relations and not self.wants(Capability.RELATIONS):
            raise ValueError("relations need the relations facet")
        return self

    def wants(self, facet: Capability) -> bool:
        """Whether a kind of facts was asked for."""
        return self.facets is None or facet in self.facets
