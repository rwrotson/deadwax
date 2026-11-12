from collections.abc import Collection

import httpx

from deadwax.core import Dossier, LookupOptions, Query, SourceInfo, run
from deadwax.sources._base import HttpAdapter
from deadwax.sources._http import HttpResources, open_cache
from deadwax.sources.bandcamp import BandcampAdapter
from deadwax.sources.config import SourcesConfig
from deadwax.sources.deezer import DeezerAdapter
from deadwax.sources.discogs import DiscogsAdapter
from deadwax.sources.itunes import ItunesAdapter
from deadwax.sources.lastfm import LastfmAdapter
from deadwax.sources.musicbrainz import MusicBrainzAdapter
from deadwax.sources.odesli import OdesliAdapter
from deadwax.sources.wikipedia import WikipediaAdapter

# Order matters: the first ready adapter that resolves a URL query reads it first.
ADAPTERS: tuple[type[HttpAdapter], ...] = (
    MusicBrainzAdapter,
    OdesliAdapter,
    ItunesAdapter,
    DeezerAdapter,
    DiscogsAdapter,
    BandcampAdapter,
    LastfmAdapter,
    WikipediaAdapter,
)


def build_adapters(config: SourcesConfig, resources: HttpResources) -> list[HttpAdapter]:
    """Create every adapter with its settings and the shared HTTP resources."""
    return [adapter(config, resources) for adapter in ADAPTERS]


def describe_sources(config: SourcesConfig | None = None) -> list[SourceInfo]:
    """List the sources with their pass, capabilities, requirements, and status."""
    adapters = build_adapters(config or SourcesConfig(), HttpResources())
    return [
        SourceInfo(
            source=adapter.name,
            pass_=adapter.pass_,
            capabilities=sorted(adapter.capabilities),
            requires=list(adapter.requires),
            status=adapter.status(),
        )
        for adapter in adapters
    ]


async def lookup(
    query: Query,
    config: SourcesConfig | None = None,
    *,
    include: Collection[str] | None = None,
    exclude: Collection[str] = (),
    transport: httpx.AsyncBaseTransport | None = None,
) -> Dossier:
    """Collect what the sources know about the queried record.

    `transport` replaces the network, for tests and recorded responses.
    """
    config = config or SourcesConfig()
    cache = open_cache(config.cache)
    adapters = build_adapters(config, HttpResources(cache=cache, transport=transport))
    options = LookupOptions(
        adapter_timeout=config.adapter_timeout,
        include=frozenset(include) if include is not None else None,
        exclude=frozenset(exclude),
    )
    try:
        return await run(query, adapters, options)
    finally:
        for adapter in adapters:
            await adapter.aclose()
        if cache is not None:
            cache.close()
