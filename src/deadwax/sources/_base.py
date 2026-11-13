import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from deadwax.core import (
    Capability,
    Entity,
    EntityKind,
    EntityType,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Requirement,
    Scope,
    SourceGroup,
    SourceState,
    SourceStatus,
    Verdict,
    compare,
    recognize_url,
    trace,
)
from deadwax.sources._http import ClientSpec, HttpClient, HttpResources, Profile
from deadwax.sources.config import SourcesConfig, SourceSettings

# Search results listed in a `search.pick` or `search.ranked` event.
TRACED_HITS = 25

logger = logging.getLogger(__name__)


class HttpAdapter(ABC):
    """Base for adapters that talk to one source through an `HttpClient`."""

    name: str
    group: SourceGroup
    pass_: Pass
    capabilities: frozenset[Capability]
    requires: tuple[Requirement, ...] = ()
    profile: Profile = Profile.API
    # User-Agent replacing the profile's one unless the source's settings name another.
    default_user_agent: str | None = None
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
                source=self.name,
                state=SourceState.MISSING_CREDENTIAL,
                detail=missing,
            )
        return SourceStatus(source=self.name, state=SourceState.READY)

    def resolves(self, query: Query) -> bool:  # noqa: ARG002 -- the protocol's signature
        """Whether this adapter reads the page behind the query URL; none by default."""
        return False

    def headers(self) -> Mapping[str, str]:
        """Extra headers for every request, such as authorization."""
        return {}

    def user_agent(self) -> str | None:
        """User-Agent replacing the profile's one, if any."""
        return self.settings.user_agent or self.default_user_agent

    def client_spec(self, profile: Profile) -> ClientSpec:
        """Describe a client of this adapter with the given profile."""
        headers = dict(self.headers())
        if (user_agent := self.user_agent()) is not None:
            headers["user-agent"] = user_agent
        return ClientSpec(self.name, profile, headers, self.secret_params)

    @property
    def client(self) -> HttpClient:
        """HTTP client of this adapter, created on first use."""
        if self._client is None:
            self._client = HttpClient(self.client_spec(self.profile), self.config, self.resources)
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
    ("junodownload.com", "junodownload"),
    ("juno.co.uk", "juno"),
    ("hardwax.com", "hardwax"),
    ("phonicarecords.com", "phonica"),
    ("soundohm.com", "soundohm"),
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


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search result: its page and the record it lists."""

    url: str
    key: RecordKey


def pick_hit(reference: RecordKey, hits: Iterable[SearchHit]) -> SearchHit | None:
    """Return the first hit of the record, else the first of another version of it.

    The merge turns another version into a relation and a version discrepancy.
    """
    seen: list[dict[str, object]] = []
    picked = other_version = None
    for hit in hits:
        verdict = compare(reference, hit.key).verdict
        seen.append(
            {"url": hit.url, "artist": hit.key.artist, "title": hit.key.title, "verdict": verdict},
        )
        if verdict is Verdict.MATCH:
            picked = hit
            break
        if verdict is Verdict.OTHER_VERSION and other_version is None:
            other_version = hit
    picked = picked or other_version

    trace(
        logger,
        "search.pick",
        reference=reference.describe(),
        hits=seen[:TRACED_HITS],
        compared=len(seen),
        picked=None if picked is None else picked.url,
    )
    return picked


def track_on_release(
    release: RecordCandidate,
    tracks: Iterable[tuple[str, str]],
    reference: RecordKey,
    provenance: Provenance,
) -> tuple[RecordCandidate, Relation]:
    """Describe the queried track by its entry on a release page and relate it to the release."""
    for artist, title in tracks:
        listed = RecordKey(artist=artist, title=title, kind=EntityKind.TRACK)
        if compare(reference, listed).verdict is not Verdict.NO_MATCH:
            break
    else:
        raise NotFoundError("the release does not list the track", url=provenance.url)
    track = release.model_copy(update={"kind": EntityKind.TRACK, "artist": artist, "title": title})
    relation = Relation(
        kind=RelationKind.APPEARS_ON,
        scope=Scope.RELEASE,
        target=Entity(
            type=EntityType.RELEASE,
            name=release.title,
            artist=release.artist,
            date=release.date,
            url=release.url,
        ),
        sources=[provenance],
    )
    return track, relation


class SearchPageAdapter(HttpAdapter):
    """Base for HTML sources that search, pick a result through the matching gate, read its page.

    The page comes from the query URL, a link an earlier pass found, or a search, in that order.
    """

    profile = Profile.BROWSER

    @property
    def search_client(self) -> HttpClient:
        """Client used for search; sources with JSON feeds may override it."""
        return self.client

    # Service name of the source's pages, as `service_for_url` gives it.
    service: str | None = None

    def resolves(self, query: Query) -> bool:
        """Pages of the source's own service."""
        return (
            self.service is not None
            and query.url is not None
            and service_for_url(query.url) == self.service
        )

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Find the record's page and read it."""
        key = search_key(query, context)
        url = await self._page_url(query, context, key)
        response = await self.client.get(url)
        return self.read_page(response.content, response.url, key)

    async def _page_url(self, query: Query, context: LookupContext, key: RecordKey | None) -> str:
        if query.url is not None and self.resolves(query):
            return query.url
        if self.service is not None and (known := context.urls(self.service)):
            return known[0]
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        url = await self.search(key)
        if url is None:
            raise NotFoundError(f"no matching {self.name} record")
        return url

    async def search(self, key: RecordKey) -> str | None:
        """Search the source and return the page of the record, if a result matches."""
        url, params = self.search_request(key)
        response = await self.search_client.get(url, params=params)
        hit = pick_hit(key, self.search_hits(response.content, response.url))
        return None if hit is None else urljoin(response.url, hit.url)

    @abstractmethod
    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """URL and query parameters of the search for a record."""

    @abstractmethod
    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:
        """Read the results of a search page; their URLs may be relative to it."""

    @abstractmethod
    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read the facts of the record's page."""
