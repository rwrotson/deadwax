from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    model_validator,
)

DEFAULT_CONTACT = "https://github.com/rwrotson/deadwax"

# Proxy setting that connects without a proxy, ignoring the environment.
DIRECT = "direct"

_PROXY_SCHEMES = frozenset({"http", "https"})


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _check_proxy(value: SecretStr) -> SecretStr:
    proxy = value.get_secret_value()
    if proxy == DIRECT:
        return value
    try:
        parts = urlsplit(proxy)
        valid = parts.scheme in _PROXY_SCHEMES and bool(parts.hostname) and parts.port is not None
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("expected 'direct' or an http:// or https:// proxy URL with a port")
    return value


# Secret because a proxy URL may carry a user name and password.
type Proxy = Annotated[SecretStr, AfterValidator(_check_proxy)]


def _split_names(value: object) -> object:
    """Read a comma-separated string of names as a tuple; other values pass unchanged."""
    if isinstance(value, str):
        return tuple(name.strip() for name in value.split(",") if name.strip())
    return value


# Source and group names, given as a sequence or as one comma-separated string.
type SourceNames = Annotated[tuple[str, ...], BeforeValidator(_split_names)]

# Sources a lookup runs when no source list is given. Deezer is left out: Akamai blocks its pages.
DEFAULT_SOURCES: tuple[str, ...] = (
    "musicbrainz",
    "itunes",
    "odesli",
    "bandcamp",
    "wikipedia",
    "lastfm",
    "discogs",
    "listenbrainz",
    "secondhandsongs",
    "kexp",
    "spotify",
    "youtube",
    "genius",
)


class Escalation(StrEnum):
    """Transport available to an HTML adapter."""

    HTTPX = "httpx"
    IMPERSONATE = "impersonate"
    BROWSER = "browser"
    PATCHRIGHT = "patchright"
    NODRIVER = "nodriver"


def _normalize_transports(value: tuple[Escalation, ...]) -> tuple[Escalation, ...]:
    """Read 'patchright' as 'browser' and reject repeated transports."""
    steps = tuple(Escalation.BROWSER if step is Escalation.PATCHRIGHT else step for step in value)
    if len(steps) != len(set(steps)):
        raise ValueError("HTML transports must be distinct ('patchright' is 'browser')")
    return steps


# Ordered HTML transports; 'patchright' is another name of 'browser'.
type Transports = Annotated[tuple[Escalation, ...], AfterValidator(_normalize_transports)]

DEFAULT_HTML_TRANSPORTS: tuple[Escalation, ...] = (
    Escalation.HTTPX,
    Escalation.IMPERSONATE,
    Escalation.BROWSER,
    Escalation.NODRIVER,
)


class HttpSettings(_Model):
    """HTTP behaviour shared by all adapters."""

    timeout: float = Field(default=15.0, gt=0, description="Seconds per HTTP request")
    contact: str = Field(
        default=DEFAULT_CONTACT,
        description="URL or e-mail address sent in the User-Agent of API requests",
    )
    retries: int = Field(default=3, ge=0, description="Retries after 429, 5xx, or network errors")
    retry_base: float = Field(
        default=1.0,
        gt=0,
        description="Seconds of the first backoff; it doubles on each retry",
    )
    max_retry_wait: float = Field(
        default=60.0,
        ge=0,
        description="Longest Retry-After wait, in seconds, before giving up",
    )
    escalation: Transports = Field(
        default=(Escalation.IMPERSONATE, Escalation.BROWSER, Escalation.NODRIVER),
        description="Additional HTML transports allowed globally; source order is preserved",
    )
    browser_headless: bool = Field(
        default=True,
        description="Run Patchright and Nodriver without a visible browser window",
    )
    patchright_channel: str = Field(
        default="chromium",
        pattern="^(chromium|chrome)$",
        description=(
            "Patchright browser: bundled Chromium or installed Chrome with a temporary profile"
        ),
    )
    patchright_profile_dir: Path | None = Field(
        default=None,
        description="Optional dedicated Chrome profile for Patchright, retained between lookups",
    )
    browser_challenge_wait: float = Field(
        default=5.0,
        ge=0,
        description="Seconds to wait for a challenge or required page state in a browser",
    )
    headed_fallback: bool = Field(
        default=True,
        description=(
            "Retry a challenged headless Patchright or Nodriver page in a visible browser "
            "and keep the source headed for the rest of the lookup"
        ),
    )
    headed_challenge_wait: float = Field(
        default=60.0,
        ge=0,
        description=(
            "Seconds a visible browser waits, after the automatic wait, for a challenge "
            "completed by hand; not counted in the adapter timeout"
        ),
    )
    nodriver_browser_path: Path | None = Field(
        default=None,
        description="Chrome executable for Nodriver; unset uses its system discovery",
    )
    nodriver_profile_dir: Path | None = Field(
        default=None,
        description="Optional dedicated Chrome profile for Nodriver, retained between lookups",
    )
    nodriver_sandbox: bool = Field(
        default=True,
        description="Enable Chrome's sandbox for Nodriver; disable only for a trusted browser",
    )
    max_response_bytes: int = Field(
        default=10_000_000,
        gt=0,
        description="Responses larger than this are rejected",
    )
    proxy: Proxy | None = Field(
        default=None,
        description=(
            "Proxy of every source: 'direct' for none, or an http(s):// URL; "
            "unset: HTTP(S)_PROXY, ALL_PROXY and NO_PROXY from the environment"
        ),
    )

    @model_validator(mode="after")
    def distinct_browser_profiles(self) -> Self:
        """Keep the two browser transports from sharing one writable profile."""
        if (
            self.patchright_profile_dir is not None
            and self.nodriver_profile_dir is not None
            and self.patchright_profile_dir.expanduser().resolve()
            == self.nodriver_profile_dir.expanduser().resolve()
        ):
            raise ValueError("Patchright and Nodriver must use separate profile directories")
        return self


class CacheSettings(_Model):
    """On-disk cache of HTTP responses."""

    enabled: bool = Field(default=True, description="Read and write the response cache")
    path: Path | None = Field(
        default=None,
        description="SQLite file of the cache; no cache when unset",
    )
    ttl: float = Field(default=7 * 86400, ge=0, description="Seconds a response stays fresh")
    not_found_ttl: float = Field(
        default=86400,
        ge=0,
        description="Seconds a 'not found' response stays fresh",
    )
    blocked_ttl: float = Field(
        default=86400,
        ge=0,
        description="Seconds a page refused by bot protection is not requested again",
    )


def _rate(default: float, note: str = "") -> Any:  # noqa: ANN401 -- a Pydantic field
    return Field(default=default, gt=0, description=f"Requests per second{note}")


def _transports(*default: Escalation) -> Any:  # noqa: ANN401 -- a Pydantic field
    return Field(
        default=default,
        description="Ordered HTML transports, filtered by http.escalation",
    )


def _headless(default: bool | None = None) -> Any:  # noqa: ANN401 -- a Pydantic field
    return Field(
        default=default,
        description="Browser mode of this source; unset uses http.browser_headless",
    )


class SourceSettings(_Model):
    """Settings of one source; each source's subclass holds its defaults."""

    enabled: bool = Field(default=True, description="Use this source")
    rate: float = _rate(1.0)
    ttl: float | None = Field(
        default=None,
        ge=0,
        description="Cache lifetime in seconds; cache.ttl when unset",
    )
    user_agent: str | None = Field(
        default=None,
        description="User-Agent of this source's requests; the source default when unset",
    )
    proxy: Proxy | None = Field(
        default=None,
        description="Proxy of this source: 'direct' or an http(s):// URL; http.proxy when unset",
    )
    html_transports: Transports = _transports(*DEFAULT_HTML_TRANSPORTS)
    browser_headless: bool | None = _headless()


# Request rates follow each source's limits: MusicBrainz 1/s, iTunes Search about 20/min,
# Deezer 50 per 5 s, Discogs 60/min with a token, SecondHandSongs 10-20/min without a key;
# YouTube search costs 100 of 10,000 daily quota units; scraped pages are fetched slowly on
# purpose.


class MusicBrainzSettings(SourceSettings):
    """Settings of the MusicBrainz source."""


class ItunesSettings(SourceSettings):
    """Settings of the iTunes Search source."""

    rate: float = _rate(0.3)


class DeezerSettings(SourceSettings):
    """Settings of the Deezer source."""

    rate: float = _rate(2.0)


class OdesliSettings(SourceSettings):
    """Settings of the Odesli (song.link) source."""

    rate: float = _rate(0.5)


class DiscogsSettings(SourceSettings):
    """Settings of the Discogs source."""

    rate: float = _rate(1.0, "; without a token and unset, 25 a minute")
    token: SecretStr | None = Field(
        default=None,
        description="Personal access token; needed for search",
    )


class BandcampSettings(SourceSettings):
    """Settings of the Bandcamp source."""

    rate: float = _rate(0.5)


class LastfmSettings(SourceSettings):
    """Settings of the Last.fm source."""

    rate: float = _rate(4.0)
    api_key: SecretStr | None = Field(default=None, description="API key")


class WikipediaSettings(SourceSettings):
    """Settings of the Wikipedia and Wikidata source."""

    rate: float = _rate(5.0)


class ListenBrainzSettings(SourceSettings):
    """Settings of the ListenBrainz source."""

    rate: float = _rate(2.0)


class SecondHandSongsSettings(SourceSettings):
    """Settings of the SecondHandSongs source."""

    rate: float = _rate(0.25)
    api_key: SecretStr | None = Field(
        default=None,
        description="API key raising the request limit; lookups work without it",
    )


class KexpSettings(SourceSettings):
    """Settings of the KEXP source."""

    rate: float = _rate(2.0)


class SpotifySettings(SourceSettings):
    """Settings of the Spotify source."""

    rate: float = _rate(2.0)
    client_id: SecretStr | None = Field(
        default=None,
        description="Client ID of a Spotify app; needed with the client secret",
    )
    client_secret: SecretStr | None = Field(
        default=None,
        description="Client secret of a Spotify app; needed with the client ID",
    )


class YouTubeSettings(SourceSettings):
    """Settings of the YouTube source."""

    api_key: SecretStr | None = Field(default=None, description="YouTube Data API key")


class GeniusSettings(SourceSettings):
    """Settings of the Genius source."""

    token: SecretStr | None = Field(default=None, description="Genius API client access token")


class SoundCloudSettings(SourceSettings):
    """Settings of the SoundCloud source."""

    client_id: SecretStr | None = Field(
        default=None,
        description="Client ID of SoundCloud's API; the web client's ID changes now and then",
    )


class BeatportSettings(SourceSettings):
    """Settings of the Beatport source."""

    rate: float = _rate(0.5)
    html_transports: Transports = _transports(
        Escalation.NODRIVER,
        Escalation.BROWSER,
        Escalation.IMPERSONATE,
        Escalation.HTTPX,
    )


class HardWaxSettings(SourceSettings):
    """Settings of the Hard Wax source."""

    rate: float = _rate(0.5)


class SoundohmSettings(SourceSettings):
    """Settings of the Soundohm source."""

    rate: float = _rate(0.5)


class JunoSettings(SourceSettings):
    """Settings of the Juno source."""

    rate: float = _rate(0.5)
    html_transports: Transports = _transports(
        Escalation.IMPERSONATE,
        Escalation.BROWSER,
        Escalation.NODRIVER,
        Escalation.HTTPX,
    )


class BleepSettings(SourceSettings):
    """Settings of the Bleep source."""

    rate: float = _rate(0.5)
    html_transports: Transports = _transports(
        Escalation.BROWSER,
        Escalation.HTTPX,
        Escalation.IMPERSONATE,
        Escalation.NODRIVER,
    )


class ForcedExposureSettings(SourceSettings):
    """Settings of the Forced Exposure source."""

    rate: float = _rate(0.5)
    html_transports: Transports = _transports(
        Escalation.BROWSER,
        Escalation.HTTPX,
        Escalation.IMPERSONATE,
        Escalation.NODRIVER,
    )


class AllMusicSettings(SourceSettings):
    """Settings of the AllMusic source."""

    rate: float = _rate(0.5)


class AlbumOfTheYearSettings(SourceSettings):
    """Settings of the Album of the Year source."""

    rate: float = _rate(0.5)


class PhonicaSettings(SourceSettings):
    """Settings of the Phonica source."""

    rate: float = _rate(0.5)
    html_transports: Transports = _transports(Escalation.BROWSER)


class BoomkatSettings(SourceSettings):
    """Settings of the Boomkat source."""

    rate: float = _rate(0.5)
    html_transports: Transports = _transports(Escalation.BROWSER)
    browser_headless: bool | None = _headless(default=False)


class NormanSettings(SourceSettings):
    """Settings of the Norman Records source."""

    rate: float = _rate(0.5)
    html_transports: Transports = _transports(Escalation.NODRIVER)
    browser_headless: bool | None = _headless(default=False)


class PressReviewsSettings(SourceSettings):
    """Settings of the press review source (Pitchfork, The Quietus, The Wire)."""

    rate: float = _rate(0.5)


class ResidentAdvisorSettings(SourceSettings):
    """Settings of the Resident Advisor source."""

    rate: float = _rate(0.5)


class NtsSettings(SourceSettings):
    """Settings of the NTS source."""

    rate: float = _rate(0.5)


class WfmuSettings(SourceSettings):
    """Settings of the WFMU source."""

    rate: float = _rate(0.5)


class RateYourMusicSettings(SourceSettings):
    """Settings of the Rate Your Music source."""

    rate: float = _rate(0.5)
    html_transports: Transports = _transports(Escalation.BROWSER)


class WhoSampledSettings(SourceSettings):
    """Settings of the WhoSampled source."""

    rate: float = _rate(0.5)
    html_transports: Transports = _transports(Escalation.BROWSER)
    browser_headless: bool | None = _headless(default=False)


class TracklistsSettings(SourceSettings):
    """Settings of the 1001Tracklists source."""

    rate: float = _rate(0.125)
    html_transports: Transports = _transports(Escalation.BROWSER)
    browser_headless: bool | None = _headless(default=False)


class PerSourceSettings(_Model):
    """Settings of each source, by source name."""

    musicbrainz: MusicBrainzSettings = MusicBrainzSettings()
    itunes: ItunesSettings = ItunesSettings()
    deezer: DeezerSettings = DeezerSettings()
    odesli: OdesliSettings = OdesliSettings()
    discogs: DiscogsSettings = DiscogsSettings()
    bandcamp: BandcampSettings = BandcampSettings()
    lastfm: LastfmSettings = LastfmSettings()
    wikipedia: WikipediaSettings = WikipediaSettings()
    listenbrainz: ListenBrainzSettings = ListenBrainzSettings()
    secondhandsongs: SecondHandSongsSettings = SecondHandSongsSettings()
    kexp: KexpSettings = KexpSettings()
    spotify: SpotifySettings = SpotifySettings()
    youtube: YouTubeSettings = YouTubeSettings()
    genius: GeniusSettings = GeniusSettings()
    soundcloud: SoundCloudSettings = SoundCloudSettings()
    beatport: BeatportSettings = BeatportSettings()
    hardwax: HardWaxSettings = HardWaxSettings()
    soundohm: SoundohmSettings = SoundohmSettings()
    juno: JunoSettings = JunoSettings()
    bleep: BleepSettings = BleepSettings()
    forcedexposure: ForcedExposureSettings = ForcedExposureSettings()
    allmusic: AllMusicSettings = AllMusicSettings()
    albumoftheyear: AlbumOfTheYearSettings = AlbumOfTheYearSettings()
    phonica: PhonicaSettings = PhonicaSettings()
    boomkat: BoomkatSettings = BoomkatSettings()
    norman: NormanSettings = NormanSettings()
    pressreviews: PressReviewsSettings = PressReviewsSettings()
    ra: ResidentAdvisorSettings = ResidentAdvisorSettings()
    nts: NtsSettings = NtsSettings()
    wfmu: WfmuSettings = WfmuSettings()
    rateyourmusic: RateYourMusicSettings = RateYourMusicSettings()
    whosampled: WhoSampledSettings = WhoSampledSettings()
    tracklists: TracklistsSettings = TracklistsSettings()

    def of(self, source: str) -> SourceSettings:
        """Return a source's settings; an unknown name gets the base defaults."""
        settings = getattr(self, source, None)
        return settings if isinstance(settings, SourceSettings) else SourceSettings()


class ClientSettings(_Model):
    """HTTP settings of one source after its own settings override the shared ones."""

    http: HttpSettings
    rate: float = Field(gt=0)
    ttl: float = Field(ge=0)
    not_found_ttl: float = Field(ge=0)
    blocked_ttl: float = Field(ge=0)
    proxy: Proxy | None = None
    html_transports: tuple[Escalation, ...]

    @property
    def proxy_url(self) -> str | None:
        """Return the proxy setting: 'direct', a URL, or None for the environment."""
        return self.proxy.get_secret_value() if self.proxy is not None else None


class LookupConfig(_Model):
    """Configuration of a lookup: sources, the HTTP stack, and the cache."""

    http: HttpSettings = HttpSettings()
    cache: CacheSettings = CacheSettings()
    adapter_timeout: float = Field(default=30.0, gt=0, description="Seconds per source lookup")
    default_sources: SourceNames = Field(
        default=DEFAULT_SOURCES,
        description="Source and group names a lookup runs when no source list is given",
    )
    concurrency: int = Field(default=8, ge=1, description="Sources queried at once in a lookup")
    sources: PerSourceSettings = PerSourceSettings()

    def client_settings(self, source: str) -> ClientSettings:
        """Resolve the HTTP settings of a source's clients."""
        settings = self.sources.of(source)
        allowed = {Escalation.HTTPX, *self.http.escalation}
        headless = settings.browser_headless
        if headless is None:
            headless = self.http.browser_headless
        return ClientSettings(
            http=self.http.model_copy(update={"browser_headless": headless}),
            rate=settings.rate,
            ttl=self.cache.ttl if settings.ttl is None else settings.ttl,
            not_found_ttl=self.cache.not_found_ttl,
            blocked_ttl=self.cache.blocked_ttl,
            proxy=self.http.proxy if settings.proxy is None else settings.proxy,
            html_transports=tuple(step for step in settings.html_transports if step in allowed),
        )
