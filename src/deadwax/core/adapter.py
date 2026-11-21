from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import Protocol, assert_never

from pydantic import BaseModel, ConfigDict

from deadwax.core.models import (
    Identity,
    Link,
    Partial,
    RecordIdentity,
    ReviewLink,
    SourceAccess,
)
from deadwax.core.query import (
    AlbumQuery,
    ArtistQuery,
    EntityKind,
    IdKind,
    LabelQuery,
    Query,
    TrackQuery,
    UnresolvedQuery,
    normalize_code,
)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Pass(StrEnum):
    """Lookup pass in which an adapter runs."""

    IDENTITY = "identity"
    ENRICH = "enrich"

    # Runs after enrichment and starts from the links it found.
    LINKS = "links"


class Capability(StrEnum):
    """Kind of facts an adapter can contribute.

    For artists and labels, texts are biographies and profiles, tags are genres, relations
    are members, labels, and similar artists, metrics are listener counts, and links are
    service pages; credits and previews apply only to tracks and albums.
    """

    IDENTITY = "identity"
    LINKS = "links"

    # Links that carry a playable preview URL.
    PREVIEWS = "previews"

    TAGS = "tags"
    CREDITS = "credits"
    TEXTS = "texts"
    RELATIONS = "relations"
    METRICS = "metrics"


class SourceGroup(StrEnum):
    """Kind of source, selectable by name like a source."""

    # The v1 sources.
    CORE = "core"

    SHOPS = "shops"
    PRESS = "press"
    CATALOGUES = "catalogues"
    RADIO = "radio"
    STREAMING = "streaming"
    SAMPLES = "samples"


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
    group: SourceGroup
    pass_: Pass
    capabilities: list[Capability]
    kinds: list[EntityKind]
    requires: list[Requirement]
    status: SourceStatus
    access: SourceAccess

    # Whether a lookup without an explicit source list runs the adapter.
    default: bool


class LookupContext(_Model):
    """What earlier passes established about the record."""

    query: Query
    identity: Identity = RecordIdentity()
    links: list[Link] = []
    review_links: list[ReviewLink] = []

    # Facets the request asked for; unset means all of them.
    facets: frozenset[Capability] | None = None

    @property
    def kind(self) -> EntityKind | None:
        """Record kind from the query, else from earlier passes."""
        return self.query.kind or self.identity.kind

    def wants(self, facet: Capability) -> bool:
        """Whether the request asked for a kind of facts, so an adapter may skip the rest."""
        return self.facets is None or facet in self.facets

    def id(self, kind: IdKind) -> str | None:
        """Return the first known identifier of a kind, from the query or earlier passes."""
        if kind in self.query.ids:
            return self.query.ids[kind]
        return next((i.value for i in self.identity.external_ids if i.kind is kind), None)

    def isrcs(self) -> list[str]:
        """Return the known ISRCs: the query's first, then those of earlier passes."""
        codes = [self.query.ids[IdKind.ISRC]] if IdKind.ISRC in self.query.ids else []
        if isinstance(self.identity, RecordIdentity):
            codes += [isrc.value for isrc in self.identity.isrcs]
        unique: dict[str, str] = {}
        for code in codes:
            unique.setdefault(normalize_code(code), code)
        return list(unique.values())

    def urls(self, service: str) -> list[str]:
        """Return the known link URLs of a service."""
        return [link.url for link in self.links if link.service == service]


class TrackLookup(Protocol):
    """Lookup of a track by one source."""

    def __call__(self, query: TrackQuery, context: LookupContext, /) -> Awaitable[Partial]:
        """Find the track and return what the source knows about it."""
        ...


class AlbumLookup(Protocol):
    """Lookup of an album by one source."""

    def __call__(self, query: AlbumQuery, context: LookupContext, /) -> Awaitable[Partial]:
        """Find the album and return what the source knows about it."""
        ...


class ArtistLookup(Protocol):
    """Lookup of an artist by one source."""

    def __call__(self, query: ArtistQuery, context: LookupContext, /) -> Awaitable[Partial]:
        """Find the artist and return what the source knows about them."""
        ...


class LabelLookup(Protocol):
    """Lookup of a label by one source."""

    def __call__(self, query: LabelQuery, context: LookupContext, /) -> Awaitable[Partial]:
        """Find the label and return what the source knows about it."""
        ...


class UnresolvedLookup(Protocol):
    """Lookup of a page whose record kind is not known yet."""

    def __call__(self, query: UnresolvedQuery, context: LookupContext, /) -> Awaitable[Partial]:
        """Read the page and return what the source knows about its record."""
        ...


type BoundLookup = Callable[[LookupContext], Awaitable[Partial]]


@dataclass(frozen=True, slots=True)
class Lookups:
    """Lookups of an adapter by record kind; an unset slot means the source does not look it up."""

    track: TrackLookup | None = None
    album: AlbumLookup | None = None
    artist: ArtistLookup | None = None
    label: LabelLookup | None = None

    # Reads a query whose kind neither the query nor earlier passes established.
    unresolved: UnresolvedLookup | None = None

    @property
    def kinds(self) -> frozenset[EntityKind]:
        """Record kinds the adapter looks up."""
        return frozenset(kind for kind in EntityKind if self.supports(kind))

    def supports(self, kind: EntityKind | None) -> bool:
        """Whether the adapter looks up a record kind, or a record of unknown kind for None."""
        match kind:
            case EntityKind.TRACK:
                return self.track is not None
            case EntityKind.ALBUM:
                return self.album is not None
            case EntityKind.ARTIST:
                return self.artist is not None
            case EntityKind.LABEL:
                return self.label is not None
            case None:
                return self.unresolved is not None
            case _:
                assert_never(kind)

    def bind(self, query: Query) -> BoundLookup | None:
        """Return the lookup of the query's kind applied to the query, if the adapter has one."""
        match query:
            case TrackQuery():
                return None if self.track is None else partial(self.track, query)
            case AlbumQuery():
                return None if self.album is None else partial(self.album, query)
            case ArtistQuery():
                return None if self.artist is None else partial(self.artist, query)
            case LabelQuery():
                return None if self.label is None else partial(self.label, query)
            case UnresolvedQuery():
                return None if self.unresolved is None else partial(self.unresolved, query)
            case _:
                assert_never(query)


class Adapter(Protocol):
    """Source of facts about a record."""

    @property
    def name(self) -> str:
        """Source name used in provenance and errors."""
        ...

    @property
    def group(self) -> SourceGroup:
        """Group the source belongs to."""
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

    @property
    def lookups(self) -> Lookups:
        """Lookups the adapter runs, one per record kind it supports."""
        ...
