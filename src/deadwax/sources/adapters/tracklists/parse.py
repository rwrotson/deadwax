from deadwax.core import (
    EntityKind,
    NotFoundError,
    Partial,
    RecordCandidate,
    RecordKey,
    SourceError,
    Verdict,
    compare,
)
from deadwax.sources._html import Node, attribute, parse_html, text_of
from deadwax.sources._search import SearchHit

SOURCE = "tracklists"
ROOT = "https://www.1001tracklists.com"
SEARCH = f"{ROOT}/search/result.php"
MAX_SETS = 5


def row_key(row: Node) -> RecordKey | None:
    """Record listed in a tracklist row."""
    artist = attribute(row.css_first('meta[itemprop="byArtist"]'), "content")
    full = attribute(row.css_first('meta[itemprop="name"]'), "content")
    if not artist or not full:
        return None
    title = full.removeprefix(f"{artist} - ")
    return RecordKey(artist=artist, title=title, kind=EntityKind.TRACK)


def search_hits(content: bytes) -> list[SearchHit]:
    """Read the record labels and links shown in search results."""
    hits = []
    for link in parse_html(content).css('a[href*="/track/"]'):
        label = text_of(link)
        href = attribute(link, "href")
        if not label or not href or " - " not in label:
            continue
        artist, title = label.split(" - ", 1)
        hits.append(
            SearchHit(
                url=href,
                key=RecordKey(artist=artist, title=title, kind=EntityKind.TRACK),
            ),
        )
    return hits


def page_partial(content: bytes, url: str, key: RecordKey | None) -> Partial:
    """Verify the track page before any set contributes relations."""
    page = parse_html(content)
    heading = page.css_first("h1#pageTitle")
    artist = text_of(heading.css_first("a[href*='/artist/']")) if heading else None
    if heading is None or not artist:
        raise SourceError("1001Tracklists page names no track", url=url)
    name = heading.text(deep=False, strip=True).removeprefix("-").strip()
    if (
        key is not None
        and compare(key, RecordKey(artist=artist, title=name, kind=EntityKind.TRACK)).verdict
        is not Verdict.MATCH
    ):
        raise NotFoundError("1001Tracklists page is another version", url=url)
    return Partial(
        source=SOURCE,
        candidate=RecordCandidate(kind=EntityKind.TRACK, artist=artist, title=name, url=url),
    )
