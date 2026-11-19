from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.albumoftheyear import AlbumOfTheYearAdapter
from deadwax.sources.adapters.allmusic import AllMusicAdapter
from deadwax.sources.adapters.bandcamp import BandcampAdapter
from deadwax.sources.adapters.beatport import BeatportAdapter
from deadwax.sources.adapters.bleep import BleepAdapter
from deadwax.sources.adapters.boomkat import BoomkatAdapter
from deadwax.sources.adapters.deezer import DeezerAdapter
from deadwax.sources.adapters.discogs import DiscogsAdapter
from deadwax.sources.adapters.forcedexposure import ForcedExposureAdapter
from deadwax.sources.adapters.genius import GeniusAdapter
from deadwax.sources.adapters.hardwax import HardWaxAdapter
from deadwax.sources.adapters.itunes import ItunesAdapter
from deadwax.sources.adapters.juno import JunoAdapter
from deadwax.sources.adapters.kexp import KexpAdapter
from deadwax.sources.adapters.lastfm import LastfmAdapter
from deadwax.sources.adapters.listenbrainz import ListenBrainzAdapter
from deadwax.sources.adapters.musicbrainz import MusicBrainzAdapter
from deadwax.sources.adapters.norman import NormanAdapter
from deadwax.sources.adapters.nts import NtsAdapter
from deadwax.sources.adapters.odesli import OdesliAdapter
from deadwax.sources.adapters.phonica import PhonicaAdapter
from deadwax.sources.adapters.pressreviews import PressAdapter
from deadwax.sources.adapters.ra import ResidentAdvisorAdapter
from deadwax.sources.adapters.rateyourmusic import RateYourMusicAdapter
from deadwax.sources.adapters.secondhandsongs import SecondHandSongsAdapter
from deadwax.sources.adapters.soundcloud import SoundCloudAdapter
from deadwax.sources.adapters.soundohm import SoundohmAdapter
from deadwax.sources.adapters.spotify import SpotifyAdapter
from deadwax.sources.adapters.tracklists import TracklistsAdapter
from deadwax.sources.adapters.wfmu import WfmuAdapter
from deadwax.sources.adapters.whosampled import WhoSampledAdapter
from deadwax.sources.adapters.wikipedia import WikipediaAdapter
from deadwax.sources.adapters.youtube import YouTubeAdapter
from deadwax.sources.config import LookupConfig

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


def build_adapters(config: LookupConfig, resources: HttpResources) -> list[HttpAdapter]:
    """Create every adapter with its settings and the shared HTTP resources."""
    return [adapter(config, resources) for adapter in ADAPTERS]
