import logging
from abc import abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urljoin

from deadwax.core import (
    Entity,
    EntityKind,
    EntityType,
    LookupContext,
    NotFoundError,
    Partial,
    Provenance,
    Query,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    TraceEvent,
    Verdict,
    compare,
    trace,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import HttpClient, Profile

# Search results listed in a `search.pick` or `search.ranked` event.
TRACED_HITS = 25

logger = logging.getLogger(__name__)


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
        TraceEvent.SEARCH_PICK,
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
