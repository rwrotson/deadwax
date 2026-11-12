import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from urllib.parse import urlsplit

from deadwax.core import (
    Capability,
    EntityKind,
    LinkTarget,
    LookupContext,
    Partial,
    Pass,
    Query,
    RecordKey,
    Requirement,
    SourceState,
    SourceStatus,
    recognize_url,
)
from deadwax.sources._http import ClientSpec, HttpClient, HttpResources, Profile
from deadwax.sources.config import SourcesConfig, SourceSettings


class HttpAdapter(ABC):
    """Base for adapters that talk to one source through an `HttpClient`."""

    name: str
    pass_: Pass
    capabilities: frozenset[Capability]
    requires: tuple[Requirement, ...] = ()
    profile: Profile = Profile.API
    secret_params: frozenset[str] = frozenset()

    def __init__(self, config: SourcesConfig, resources: HttpResources) -> None:
        self.config = config
        self.resources = resources
        self._client: HttpClient | None = None

    @property
    def settings(self) -> SourceSettings:
        """Settings of this source."""
        settings: SourceSettings = getattr(self.config, self.name)
        return settings

    def missing_credential(self) -> str | None:
        """Describe a missing credential the adapter cannot run without, if any."""
        return None

    def status(self) -> SourceStatus:
        """Report whether the adapter is enabled and has what it needs."""
        if not self.settings.enabled:
            return SourceStatus(source=self.name, state=SourceState.DISABLED)
        missing = self.missing_credential()
        if missing is not None:
            return SourceStatus(
                source=self.name, state=SourceState.MISSING_CREDENTIAL, detail=missing
            )
        return SourceStatus(source=self.name, state=SourceState.READY)

    def resolves(self, query: Query) -> bool:  # noqa: ARG002 -- the protocol's signature
        """Whether this adapter reads the page behind the query URL; none by default."""
        return False

    def headers(self) -> Mapping[str, str]:
        """Extra headers for every request, such as authorization."""
        return {}

    @property
    def client(self) -> HttpClient:
        """HTTP client of this adapter, created on first use."""
        if self._client is None:
            spec = ClientSpec(self.name, self.profile, self.headers(), self.secret_params)
            self._client = HttpClient(spec, self.config, self.resources)
        return self._client

    @abstractmethod
    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Find the record and return what the source knows about it."""

    async def aclose(self) -> None:
        """Close the HTTP client if it was opened."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# Hosts of streaming and store services, matched against the end of the URL host.
_SERVICES = (
    ("open.spotify.com", "spotify"),
    ("music.apple.com", "apple_music"),
    ("itunes.apple.com", "apple_music"),
    ("deezer.com", "deezer"),
    ("tidal.com", "tidal"),
    ("music.youtube.com", "youtube_music"),
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("bandcamp.com", "bandcamp"),
    ("soundcloud.com", "soundcloud"),
    ("music.amazon.com", "amazon_music"),
    ("amazon.com", "amazon"),
    ("beatport.com", "beatport"),
    ("qobuz.com", "qobuz"),
    ("napster.com", "napster"),
    ("pandora.com", "pandora"),
    ("audiomack.com", "audiomack"),
    ("boomkat.com", "boomkat"),
    ("junodownload.com", "juno"),
    ("7digital.com", "7digital"),
)


def service_for_url(url: str) -> str | None:
    """Name the streaming or store service a URL belongs to, if it is a known one."""
    host = (urlsplit(url).hostname or "").lower()
    for suffix, service in _SERVICES:
        if host == suffix or host.endswith(f".{suffix}"):
            return service
    return None


def link_target(url: str, default: LinkTarget) -> LinkTarget:
    """Tell whether a service URL opens a track or an album, falling back to a default."""
    kind, _ = recognize_url(url)
    if kind is EntityKind.TRACK:
        return LinkTarget.TRACK
    if kind is EntityKind.ALBUM:
        return LinkTarget.ALBUM
    if re.search(r"/(?:artist|channel|user)/", urlsplit(url).path):
        return LinkTarget.ARTIST
    return default


def search_key(query: Query, context: LookupContext) -> RecordKey | None:
    """Return what to search for: the query text, or what an earlier pass found for a URL query."""
    kind = query.kind or context.identity.kind
    if query.artist and query.title:
        return RecordKey(artist=query.artist, title=query.title, kind=kind)
    identity = context.identity
    if identity.artist is None or identity.title is None:
        return None
    return RecordKey(
        artist=identity.artist.value,
        title=identity.title.value,
        kind=kind,
        version=identity.version,
    )
