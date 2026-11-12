"""Source adapters, HTTP stack and lookup composition."""

from .config import (
    DEFAULT_CONTACT,
    DEFAULT_RATES,
    CacheSettings,
    DiscogsSettings,
    Escalation,
    HttpSettings,
    LastfmSettings,
    SourcesConfig,
    SourceSettings,
)
from .lookup import build_adapters, describe_sources, lookup

__all__ = [
    "DEFAULT_CONTACT",
    "DEFAULT_RATES",
    "CacheSettings",
    "DiscogsSettings",
    "Escalation",
    "HttpSettings",
    "LastfmSettings",
    "SourceSettings",
    "SourcesConfig",
    "build_adapters",
    "describe_sources",
    "lookup",
]
