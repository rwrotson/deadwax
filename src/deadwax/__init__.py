import logging
from typing import TYPE_CHECKING

from .core import (
    AdapterError,
    Capability,
    ConfigurationError,
    Credit,
    DeadwaxError,
    Discrepancy,
    Dossier,
    Entity,
    EntityKind,
    EntityType,
    ErrorKind,
    ExternalId,
    Identity,
    IdKind,
    InvalidQueryError,
    LabelRef,
    Link,
    LinkTarget,
    Metric,
    MetricKind,
    Pass,
    Provenance,
    Query,
    Rating,
    Relation,
    RelationKind,
    Requirement,
    Scope,
    Sourced,
    SourceGroup,
    SourceInfo,
    SourceState,
    SourceStatus,
    Tag,
    TagKind,
    Text,
    TextKind,
    VersionInfo,
    VersionKind,
    parse_query,
    parse_title,
    to_markdown,
)

if TYPE_CHECKING:
    from .sources import (
        CacheSettings,
        DiscogsSettings,
        Escalation,
        HttpSettings,
        LastfmSettings,
        SecondHandSongsSettings,
        SourcesConfig,
        SourceSettings,
        describe_sources,
        lookup,
    )

# The sources layer imports httpx, which loads rich and click whenever they are installed,
# so it is imported on first use of one of its names.
_SOURCES_NAMES = frozenset(
    {
        "CacheSettings",
        "DiscogsSettings",
        "Escalation",
        "HttpSettings",
        "LastfmSettings",
        "SecondHandSongsSettings",
        "SourcesConfig",
        "SourceSettings",
        "describe_sources",
        "lookup",
    },
)


def __getattr__(name: str) -> object:
    if name in _SOURCES_NAMES:
        from . import sources  # noqa: PLC0415 -- deferred, see _SOURCES_NAMES

        return getattr(sources, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Records stay silent unless the application configures logging.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "AdapterError",
    "CacheSettings",
    "Capability",
    "ConfigurationError",
    "Credit",
    "DeadwaxError",
    "DiscogsSettings",
    "Discrepancy",
    "Dossier",
    "Entity",
    "EntityKind",
    "EntityType",
    "ErrorKind",
    "Escalation",
    "ExternalId",
    "HttpSettings",
    "IdKind",
    "Identity",
    "InvalidQueryError",
    "LabelRef",
    "LastfmSettings",
    "Link",
    "LinkTarget",
    "Metric",
    "MetricKind",
    "Pass",
    "Provenance",
    "Query",
    "Rating",
    "Relation",
    "RelationKind",
    "Requirement",
    "Scope",
    "SecondHandSongsSettings",
    "SourceGroup",
    "SourceInfo",
    "SourceSettings",
    "SourceState",
    "SourceStatus",
    "Sourced",
    "SourcesConfig",
    "Tag",
    "TagKind",
    "Text",
    "TextKind",
    "VersionInfo",
    "VersionKind",
    "describe_sources",
    "lookup",
    "parse_query",
    "parse_title",
    "to_markdown",
]
