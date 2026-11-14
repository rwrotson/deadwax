"""Source adapters, HTTP stack and lookup composition."""

from .config import (
    DEFAULT_CONTACT,
    DEFAULT_RATES,
    CacheSettings,
    DiscogsSettings,
    Escalation,
    GeniusSettings,
    HttpSettings,
    LastfmSettings,
    SecondHandSongsSettings,
    SoundCloudSettings,
    SourcesConfig,
    SourceSettings,
    SpotifySettings,
    YouTubeSettings,
)
from .lookup import build_adapters, describe_sources, lookup

__all__ = [
    "DEFAULT_CONTACT",
    "DEFAULT_RATES",
    "CacheSettings",
    "DiscogsSettings",
    "Escalation",
    "GeniusSettings",
    "HttpSettings",
    "LastfmSettings",
    "SecondHandSongsSettings",
    "SoundCloudSettings",
    "SourceSettings",
    "SourcesConfig",
    "SpotifySettings",
    "YouTubeSettings",
    "build_adapters",
    "describe_sources",
    "lookup",
]
