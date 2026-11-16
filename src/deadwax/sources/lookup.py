from collections.abc import Collection

import httpx

from deadwax.core import Dossier, LookupOptions, Query, SourceInfo, expand_names, run
from deadwax.sources._base import HttpAdapter
from deadwax.sources._http import HttpResources, open_cache
from deadwax.sources.albumoftheyear import AlbumOfTheYearAdapter
from deadwax.sources.allmusic import AllMusicAdapter
from deadwax.sources.bandcamp import BandcampAdapter
from deadwax.sources.beatport import BeatportAdapter
from deadwax.sources.bleep import BleepAdapter
from deadwax.sources.boomkat import BoomkatAdapter
from deadwax.sources.config import SourcesConfig
from deadwax.sources.deezer import DeezerAdapter
from deadwax.sources.discogs import DiscogsAdapter
from deadwax.sources.forcedexposure import ForcedExposureAdapter
from deadwax.sources.genius import GeniusAdapter
from deadwax.sources.hardwax import HardWaxAdapter
from deadwax.sources.itunes import ItunesAdapter
from deadwax.sources.juno import JunoAdapter
from deadwax.sources.kexp import KexpAdapter
from deadwax.sources.lastfm import LastfmAdapter
from deadwax.sources.listenbrainz import ListenBrainzAdapter
from deadwax.sources.musicbrainz import MusicBrainzAdapter
from deadwax.sources.norman import NormanAdapter
from deadwax.sources.nts import NtsAdapter
from deadwax.sources.odesli import OdesliAdapter
from deadwax.sources.phonica import PhonicaAdapter
from deadwax.sources.press import PressAdapter
from deadwax.sources.rateyourmusic import RateYourMusicAdapter
from deadwax.sources.residentadvisor import ResidentAdvisorAdapter
from deadwax.sources.secondhandsongs import SecondHandSongsAdapter
from deadwax.sources.soundcloud import SoundCloudAdapter
from deadwax.sources.soundohm import SoundohmAdapter
from deadwax.sources.spotify import SpotifyAdapter
from deadwax.sources.wfmu import WfmuAdapter
from deadwax.sources.whosampled import WhoSampledAdapter
from deadwax.sources.wikipedia import WikipediaAdapter
from deadwax.sources.youtube import YouTubeAdapter

# Order matters: the first ready adapter that resolves a URL query reads it first. Spotify
# reads its own URLs when it has credentials; without them MusicBrainz maps them.
ADAPTERS: tuple[type[HttpAdapter], ...] = (
    SpotifyAdapter,
    MusicBrainzAdapter,
    OdesliAdapter,
    ItunesAdapter,
    DeezerAdapter,
    DiscogsAdapter,
    BandcampAdapter,
    LastfmAdapter,
    WikipediaAdapter,
    ListenBrainzAdapter,
    SecondHandSongsAdapter,
    KexpAdapter,
    YouTubeAdapter,
    SoundCloudAdapter,
    BeatportAdapter,
    HardWaxAdapter,
    SoundohmAdapter,
    JunoAdapter,
    ForcedExposureAdapter,
    BleepAdapter,
    PhonicaAdapter,
    BoomkatAdapter,
    NormanAdapter,
    GeniusAdapter,
    AllMusicAdapter,
    AlbumOfTheYearAdapter,
    PressAdapter,
    ResidentAdvisorAdapter,
    NtsAdapter,
    WfmuAdapter,
    RateYourMusicAdapter,
    WhoSampledAdapter,
)


def build_adapters(config: SourcesConfig, resources: HttpResources) -> list[HttpAdapter]:
    """Create every adapter with its settings and the shared HTTP resources."""
    return [adapter(config, resources) for adapter in ADAPTERS]


def describe_sources(config: SourcesConfig | None = None) -> list[SourceInfo]:
    """List the sources with their group, pass, capabilities, requirements, and status.

    Raises `ConfigurationError` when the default source set names an unknown source or group.
    """
    config = config or SourcesConfig()
    adapters = build_adapters(config, HttpResources())
    defaults = expand_names(config.default_sources, adapters)
    return [
        SourceInfo(
            source=adapter.name,
            group=adapter.group,
            default=adapter.name in defaults,
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

    `include` and `exclude` take source and group names; without `include` the sources of
    `config.default_sources` run. `transport` replaces the network, for tests and recorded
    responses.
    """
    config = config or SourcesConfig()
    cache = open_cache(config.cache)
    adapters = build_adapters(config, HttpResources(cache=cache, transport=transport))
    options = LookupOptions(
        adapter_timeout=config.adapter_timeout,
        include=frozenset(include if include is not None else config.default_sources),
        exclude=frozenset(exclude),
        concurrency=config.concurrency,
    )

    try:
        return await run(query, adapters, options)
    finally:
        for adapter in adapters:
            await adapter.aclose()
        if cache is not None:
            cache.close()
