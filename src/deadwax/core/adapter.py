from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from deadwax.core.models import Identity, Link, Partial
from deadwax.core.query import IdKind, Query


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Pass(StrEnum):
    """Lookup pass in which an adapter runs."""

    IDENTITY = "identity"
    ENRICH = "enrich"

    # Runs after enrichment and starts from the links it found.
    LINKS = "links"


class Capability(StrEnum):
    """Kind of facts an adapter can contribute."""

    IDENTITY = "identity"
    LINKS = "links"
    TAGS = "tags"
    CREDITS = "credits"
    TEXTS = "texts"
    RELATIONS = "relations"


class Requirement(_Model):
    """Setting an adapter needs, such as an API key."""

    setting: str
    purpose: str


class SourceState(StrEnum):
    """Whether an adapter can run."""

    READY = "ready"
    DISABLED = "disabled"
    MISSING_CREDENTIAL = "missing_credential"
    MISSING_EXTRA = "missing_extra"


class SourceStatus(_Model):
    """State of one adapter with the reason it cannot run."""

    source: str
    state: SourceState
    detail: str | None = None

    @property
    def ready(self) -> bool:
        """Whether the adapter can run."""
        return self.state is SourceState.READY


class SourceInfo(_Model):
    """What an adapter contributes and whether it can run."""

    source: str
    pass_: Pass
    capabilities: list[Capability]
    requires: list[Requirement]
    status: SourceStatus


class LookupContext(_Model):
    """What earlier passes established about the record."""

    query: Query
    identity: Identity = Identity()
    links: list[Link] = []

    def id(self, kind: IdKind) -> str | None:
        """Return the first known identifier of a kind, from the query or earlier passes."""
        if kind in self.query.ids:
            return self.query.ids[kind]
        return next((i.value for i in self.identity.external_ids if i.kind is kind), None)

    def urls(self, service: str) -> list[str]:
        """Return the known link URLs of a service."""
        return [link.url for link in self.links if link.service == service]


class Adapter(Protocol):
    """Source of facts about a record."""

    @property
    def name(self) -> str:
        """Source name used in provenance and errors."""
        ...

    @property
    def pass_(self) -> Pass:
        """Pass in which the adapter runs."""
        ...

    @property
    def capabilities(self) -> frozenset[Capability]:
        """Kinds of facts the adapter can contribute."""
        ...

    @property
    def requires(self) -> tuple[Requirement, ...]:
        """Settings the adapter needs for some or all of its lookups."""
        ...

    def status(self) -> SourceStatus:
        """Report whether the adapter can run with its configuration."""
        ...

    def resolves(self, query: Query) -> bool:
        """Whether the adapter reads the page or entity behind the query URL."""
        ...

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Find the record and return what the source knows about it."""
        ...
