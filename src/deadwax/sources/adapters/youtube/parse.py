import html
import logging
import re

from deadwax.core import (
    EntityKind,
    Link,
    LinkTarget,
    Provenance,
    RecordKey,
    Verdict,
    compare,
    normalize_artist,
    trace,
)
from deadwax.sources.adapters.youtube.models import SearchItem

logger = logging.getLogger(__name__)

SOURCE = "youtube"
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
            sources=[Provenance(source=SOURCE, url=url)],
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
