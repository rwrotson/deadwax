from enum import StrEnum
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, SecretStr

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

# Sources a lookup runs when no source list is given.
DEFAULT_SOURCES: tuple[str, ...] = (
    "core",
    "listenbrainz",
    "secondhandsongs",
    "kexp",
    "spotify",
    "youtube",
)


class Escalation(StrEnum):
    """Strongest transport HTML adapters may switch to when a page is blocked."""

    NONE = "none"
    IMPERSONATE = "impersonate"
    BROWSER = "browser"


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
    escalation: Escalation | None = Field(
        default=None,
        description="Strongest transport for blocked HTML pages; unset: strongest installed",
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


class SourceSettings(_Model):
    """Settings of one source."""

    enabled: bool = Field(default=True, description="Use this source")
    rate: float | None = Field(
        default=None,
        gt=0,
        description="Requests per second; the source default when unset",
    )
    ttl: float | None = Field(
        default=None,
        ge=0,
        description="Cache lifetime in seconds; the cache default when unset",
    )
    user_agent: str | None = Field(
        default=None,
        description="User-Agent of this source's requests; the source default when unset",
    )
    proxy: Proxy | None = Field(
        default=None,
        description="Proxy of this source: 'direct' or an http(s):// URL; http.proxy when unset",
    )


class DiscogsSettings(SourceSettings):
    """Settings of the Discogs source."""

    token: SecretStr | None = Field(
        default=None,
        description="Personal access token; needed for search",
    )


class LastfmSettings(SourceSettings):
    """Settings of the Last.fm source."""

    api_key: SecretStr | None = Field(default=None, description="API key")


class SecondHandSongsSettings(SourceSettings):
    """Settings of the SecondHandSongs source."""

    api_key: SecretStr | None = Field(
        default=None,
        description="API key raising the request limit; lookups work without it",
    )


class SpotifySettings(SourceSettings):
    """Settings of the Spotify source."""

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


class SoundCloudSettings(SourceSettings):
    """Settings of the SoundCloud source."""

    client_id: SecretStr | None = Field(
        default=None,
        description="Client ID of SoundCloud's API; the web client's ID changes now and then",
    )


# Requests per second each source allows: MusicBrainz 1/s, iTunes Search about 20/min,
# Deezer 50 per 5 s, Discogs 60/min with a token, SecondHandSongs 10-20/min without a key;
# YouTube search costs 100 of 10,000 daily quota units; scraped pages are fetched slowly on
# purpose.
DEFAULT_RATES: dict[str, float] = {
    "musicbrainz": 1.0,
    "itunes": 0.3,
    "deezer": 2.0,
    "odesli": 0.5,
    "discogs": 1.0,
    "bandcamp": 0.5,
    "lastfm": 4.0,
    "wikipedia": 5.0,
    "listenbrainz": 2.0,
    "secondhandsongs": 0.25,
    "kexp": 2.0,
    "spotify": 2.0,
    "youtube": 1.0,
    "soundcloud": 1.0,
    "beatport": 0.5,
}


class SourcesConfig(_Model):
    """Configuration of all sources and the HTTP stack."""

    http: HttpSettings = HttpSettings()
    cache: CacheSettings = CacheSettings()
    adapter_timeout: float = Field(default=30.0, gt=0, description="Seconds per source lookup")
    default_sources: SourceNames = Field(
        default=DEFAULT_SOURCES,
        description="Source and group names a lookup runs when no source list is given",
    )
    concurrency: int = Field(default=8, ge=1, description="Sources queried at once in a lookup")
    musicbrainz: SourceSettings = SourceSettings()
    itunes: SourceSettings = SourceSettings()
    deezer: SourceSettings = SourceSettings()
    odesli: SourceSettings = SourceSettings()
    discogs: DiscogsSettings = DiscogsSettings()
    bandcamp: SourceSettings = SourceSettings()
    lastfm: LastfmSettings = LastfmSettings()
    wikipedia: SourceSettings = SourceSettings()
    listenbrainz: SourceSettings = SourceSettings()
    secondhandsongs: SecondHandSongsSettings = SecondHandSongsSettings()
    kexp: SourceSettings = SourceSettings()
    spotify: SpotifySettings = SpotifySettings()
    youtube: YouTubeSettings = YouTubeSettings()
    soundcloud: SoundCloudSettings = SoundCloudSettings()
    beatport: SourceSettings = SourceSettings()

    def rate(self, source: str) -> float:
        """Return the request rate of a source in requests per second."""
        settings = getattr(self, source, None)
        if isinstance(settings, SourceSettings) and settings.rate is not None:
            return settings.rate
        return DEFAULT_RATES.get(source, 1.0)

    def proxy(self, source: str) -> str | None:
        """Return the proxy setting of a source: 'direct', a URL, or None for the environment."""
        settings = getattr(self, source, None)
        if isinstance(settings, SourceSettings) and settings.proxy is not None:
            return settings.proxy.get_secret_value()
        return self.http.proxy.get_secret_value() if self.http.proxy is not None else None

    def ttl(self, source: str) -> float:
        """Return the cache lifetime of a source's responses."""
        settings = getattr(self, source, None)
        if isinstance(settings, SourceSettings) and settings.ttl is not None:
            return settings.ttl
        return self.cache.ttl
