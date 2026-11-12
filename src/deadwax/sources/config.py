from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr

DEFAULT_CONTACT = "https://github.com/rwrotson/deadwax"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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
        default=1.0, gt=0, description="Seconds of the first backoff; it doubles on each retry"
    )
    max_retry_wait: float = Field(
        default=60.0, ge=0, description="Longest Retry-After wait, in seconds, before giving up"
    )
    escalation: Escalation | None = Field(
        default=None,
        description="Strongest transport for blocked HTML pages; unset: strongest installed",
    )
    max_response_bytes: int = Field(
        default=10_000_000, gt=0, description="Responses larger than this are rejected"
    )


class CacheSettings(_Model):
    """On-disk cache of HTTP responses."""

    enabled: bool = Field(default=True, description="Read and write the response cache")
    path: Path | None = Field(
        default=None, description="SQLite file of the cache; no cache when unset"
    )
    ttl: float = Field(default=7 * 86400, ge=0, description="Seconds a response stays fresh")
    not_found_ttl: float = Field(
        default=86400, ge=0, description="Seconds a 'not found' response stays fresh"
    )


class SourceSettings(_Model):
    """Settings of one source."""

    enabled: bool = Field(default=True, description="Use this source")
    rate: float | None = Field(
        default=None, gt=0, description="Requests per second; the source default when unset"
    )
    ttl: float | None = Field(
        default=None, ge=0, description="Cache lifetime in seconds; the cache default when unset"
    )
    user_agent: str | None = Field(
        default=None,
        description="User-Agent of this source's requests; the source default when unset",
    )


class DiscogsSettings(SourceSettings):
    """Settings of the Discogs source."""

    token: SecretStr | None = Field(
        default=None, description="Personal access token; needed for search"
    )


class LastfmSettings(SourceSettings):
    """Settings of the Last.fm source."""

    api_key: SecretStr | None = Field(default=None, description="API key")


# Requests per second each source allows: MusicBrainz 1/s, iTunes Search about 20/min,
# Deezer 50 per 5 s, Discogs 60/min with a token; scraped pages are fetched slowly on purpose.
DEFAULT_RATES: dict[str, float] = {
    "musicbrainz": 1.0,
    "itunes": 0.3,
    "deezer": 2.0,
    "odesli": 0.5,
    "discogs": 1.0,
    "bandcamp": 0.5,
    "lastfm": 4.0,
    "wikipedia": 5.0,
}


class SourcesConfig(_Model):
    """Configuration of all sources and the HTTP stack."""

    http: HttpSettings = HttpSettings()
    cache: CacheSettings = CacheSettings()
    adapter_timeout: float = Field(default=30.0, gt=0, description="Seconds per source lookup")
    musicbrainz: SourceSettings = SourceSettings()
    itunes: SourceSettings = SourceSettings()
    deezer: SourceSettings = SourceSettings()
    odesli: SourceSettings = SourceSettings()
    discogs: DiscogsSettings = DiscogsSettings()
    bandcamp: SourceSettings = SourceSettings()
    lastfm: LastfmSettings = LastfmSettings()
    wikipedia: SourceSettings = SourceSettings()

    def rate(self, source: str) -> float:
        """Return the request rate of a source in requests per second."""
        settings = getattr(self, source, None)
        if isinstance(settings, SourceSettings) and settings.rate is not None:
            return settings.rate
        return DEFAULT_RATES.get(source, 1.0)

    def ttl(self, source: str) -> float:
        """Return the cache lifetime of a source's responses."""
        settings = getattr(self, source, None)
        if isinstance(settings, SourceSettings) and settings.ttl is not None:
            return settings.ttl
        return self.cache.ttl
