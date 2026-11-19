from collections.abc import Collection

import httpx

from deadwax.core import (
    Dossier,
    ErrorKind,
    LookupOptions,
    Query,
    SourceAccess,
    SourceInfo,
    expand_names,
    run,
)
from deadwax.sources._base import HttpAdapter
from deadwax.sources._http import HttpResources, Profile, open_cache
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
from deadwax.sources.tracklists import TracklistsAdapter
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
    TracklistsAdapter,
)


def build_adapters(config: SourcesConfig, resources: HttpResources) -> list[HttpAdapter]:
    """Create every adapter with its settings and the shared HTTP resources."""
    return [adapter(config, resources) for adapter in ADAPTERS]


def _access(adapter: HttpAdapter, config: SourcesConfig) -> SourceAccess:
    html = Profile.BROWSER in (adapter.profile, *adapter.additional_profiles)
    return SourceAccess(
        api=Profile.API in (adapter.profile, *adapter.additional_profiles),
        html_transports=(
            [
                "patchright" if step.value == "browser" else step.value
                for step in config.html_transports(adapter.name)
            ]
            if html
            else []
        ),
        browser_headless=config.browser_headless(adapter.name) if html else None,
        headed_fallback=html and config.http.headed_fallback,
    )


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
            **_access(adapter, config).model_dump(),
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
    resources = HttpResources(cache=cache, transport=transport)
    adapters = build_adapters(config, resources)
    options = LookupOptions(
        adapter_timeout=config.adapter_timeout,
        include=frozenset(include if include is not None else config.default_sources),
        exclude=frozenset(exclude),
        concurrency=config.concurrency,
    )

    try:
        dossier = await run(query, adapters, options)
        by_name = {adapter.name: adapter for adapter in adapters}
        errors = [
            error.model_copy(update={"access": _access(by_name[error.source], config)})
            if error.kind is ErrorKind.BLOCKED
            else error
            for error in dossier.errors
        ]
        return dossier.model_copy(update={"errors": errors})
    finally:
        for adapter in adapters:
            await adapter.aclose()
        await resources.sessions.aclose()
        if cache is not None:
            cache.close()
