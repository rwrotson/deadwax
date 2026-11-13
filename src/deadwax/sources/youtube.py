import html
import logging
import re

from pydantic import BaseModel, ConfigDict

from deadwax.core import (
    BlockedError,
    Capability,
    EntityKind,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RateLimitedError,
    RecordKey,
    Requirement,
    SourceError,
    SourceGroup,
    Verdict,
    compare,
    normalize_artist,
    trace,
)
from deadwax.sources._base import HttpAdapter, search_key

API = "https://www.googleapis.com/youtube/v3/"
SEARCH_RESULTS = "10"
LINKS = 3

# YouTube's category of music videos.
MUSIC_CATEGORY = "10"

# Channels YouTube generates for an artist's releases, named "<artist> - Topic".
_TOPIC = re.compile(r"\s+-\s+Topic$")

# Artists' official channels are often named like "RadioheadVEVO".
_VEVO = re.compile(r"\s*VEVO$", re.IGNORECASE)

# Topic channels name album playlists "Album - <title>".
_ALBUM_PREFIX = re.compile(r"^Album\s+-\s+")

# Hyphen, en dash, or em dash between artist and title.
_ARTIST_TITLE = re.compile(r"\s+[-\u2013\u2014]\s+")

# Bracketed notes of an upload that say nothing about the recording's version.
# Search does not return the Topic channels' album playlists, only listeners' "full album" ones.
_UPLOAD_NOTE = re.compile(
    r"\s*[\(\[](?:(?:official\s+)?(?:music\s+|lyrics?\s+|hd\s+|4k\s+)?"
    r"(?:video|audio|visuali[sz]er|lyrics|hd|hq|4k)|full\s+album[^\(\)\[\]]*|\d{4})[\)\]]",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


class _Api(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class ResourceId(_Api):
    """ID of a search result; videos and playlists fill different fields."""

    videoId: str | None = None  # noqa: N815 -- the API's field name
    playlistId: str | None = None  # noqa: N815 -- the API's field name


class Snippet(_Api):
    """Title and channel of a search result, HTML-escaped."""

    title: str = ""
    channelTitle: str = ""  # noqa: N815 -- the API's field name


class SearchItem(_Api):
    """One search result."""

    id: ResourceId
    snippet: Snippet


class SearchResponse(_Api):
    """Answer of the search endpoint."""

    items: list[SearchItem] = []


def _official_rank(channel: str, artist: str) -> int:
    """0 for the artist's Topic channel, 1 for a channel named like the artist, 2 otherwise."""
    if _TOPIC.search(channel):
        return 0
    if normalize_artist(_VEVO.sub("", channel)) == normalize_artist(artist):
        return 1
    return 2


def upload_key(item: SearchItem, kind: EntityKind) -> RecordKey | None:
    """Record an upload names: Topic channels name the artist, other uploads 'Artist - Title'."""
    title = _UPLOAD_NOTE.sub("", html.unescape(item.snippet.title)).strip()
    channel = html.unescape(item.snippet.channelTitle)
    if kind is EntityKind.ALBUM:
        title = _ALBUM_PREFIX.sub("", title)
    if _TOPIC.search(channel):
        return RecordKey(artist=_TOPIC.sub("", channel), title=title, kind=kind)
    parts = _ARTIST_TITLE.split(title, maxsplit=1)
    if len(parts) == 2:  # noqa: PLR2004 -- artist and title
        return RecordKey(artist=parts[0], title=parts[1], kind=kind)
    return None


def matching_links(
    items: list[SearchItem],
    reference: RecordKey,
    kind: EntityKind,
) -> list[Link]:
    """Links to uploads of exactly the record, official channels first.

    Uploads of other versions, such as live takes or covers, are dropped here: the adapter
    contributes links only, so no candidate reaches the merge gate.
    """
    found: list[tuple[int, int, Link]] = []
    seen: list[dict[str, object]] = []
    for index, item in enumerate(items):
        key = upload_key(item, kind)
        verdict = compare(reference, key).verdict if key is not None else None
        seen.append({"title": item.snippet.title, "verdict": verdict})
        url = _url(item)
        if verdict is not Verdict.MATCH or url is None or key is None:
            continue
        rank = _official_rank(html.unescape(item.snippet.channelTitle), reference.artist)
        target = LinkTarget.ALBUM if kind is EntityKind.ALBUM else LinkTarget.TRACK
        link = Link(
            service="youtube",
            url=url,
            target=target,
            sources=[Provenance(source=YouTubeAdapter.name, url=url)],
        )
        found.append((rank, index, link))
    trace(logger, "search.ranked", reference=reference.describe(), hits=seen)
    return [link for _, _, link in sorted(found, key=lambda entry: entry[:2])][:LINKS]


def _url(item: SearchItem) -> str | None:
    if item.id.videoId:
        return f"https://www.youtube.com/watch?v={item.id.videoId}"
    if item.id.playlistId:
        return f"https://www.youtube.com/playlist?list={item.id.playlistId}"
    return None


class YouTubeAdapter(HttpAdapter):
    """Links to the record's uploads on YouTube, official ones first; no other facts."""

    name = "youtube"
    pass_ = Pass.LINKS
    group = SourceGroup.STREAMING
    capabilities = frozenset({Capability.LINKS})
    requires = (Requirement(setting="youtube.api_key", purpose="every lookup"),)
    secret_params = frozenset({"key"})

    @property
    def _key(self) -> str | None:
        api_key = self.config.youtube.api_key
        return api_key.get_secret_value() if api_key is not None else None

    def missing_credential(self) -> str | None:
        """Every Data API call needs a key."""
        return None if self._key else "needs youtube.api_key"

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Search music videos, or playlists for an album, and keep uploads of the record."""
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        kind = key.kind or EntityKind.TRACK

        params = {
            "part": "snippet",
            "q": f"{key.artist} {key.title}",
            "maxResults": SEARCH_RESULTS,
            "key": self._key or "",
        }
        if kind is EntityKind.ALBUM:
            params["type"] = "playlist"
        else:
            params |= {"type": "video", "videoCategoryId": MUSIC_CATEGORY}
        try:
            response = await self.client.get(f"{API}search", params=params)
        except BlockedError, NotFoundError, RateLimitedError:
            raise
        except SourceError as error:
            message = f"YouTube refused the search ({error}): a spent daily quota or a bad key"
            raise SourceError(message, url=error.url) from None

        items = SearchResponse.model_validate_json(response.content).items
        links = matching_links(items, key, kind)
        if not links:
            raise NotFoundError("no YouTube upload of the record", url=response.url)
        return Partial(source=self.name, links=links)
