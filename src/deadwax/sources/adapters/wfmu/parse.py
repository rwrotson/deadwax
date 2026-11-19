from datetime import UTC, datetime
from urllib.parse import urljoin

from deadwax.core import (
    EntityKind,
    RecordKey,
    Verdict,
    compare,
    normalize_artist,
)
from deadwax.sources._html import parse_html, text_of

ARTISTS = "https://wfmu.org/artistbrowser.php"
MIN_CELLS = 2
MIN_INDEX_CELLS = 4
MAX_PLAYLISTS = 10

# Seconds kept for one more playlist; with less, the playlists already read are returned.
PLAYLIST_RESERVE = 5.0


def _date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%b %d %Y").replace(tzinfo=UTC).date().isoformat()
    except ValueError:
        return None


def artist_id(content: bytes, artist: str) -> str | None:
    """WFMU's identifier of an artist on its search page."""
    page = parse_html(content)
    wanted = normalize_artist(artist)
    for button in page.css('button[name="id"]'):
        if normalize_artist(text_of(button) or "") == wanted:
            return button.attributes.get("value")
    return None


def plays(content: bytes, key: RecordKey) -> list[tuple[str, str | None]]:
    """Playlist URLs that played the record, with their dates, newest first."""
    page = parse_html(content)
    found: dict[str, str | None] = {}
    for row in page.css("tr"):
        cells = row.css("td")
        if len(cells) < MIN_INDEX_CELLS:
            continue
        artist = text_of(cells[0]) or ""
        title = (text_of(cells[1]) or "").split(" (plus", maxsplit=1)[0].strip('" ')
        if (
            compare(
                key,
                RecordKey(artist=artist, title=title, kind=EntityKind.TRACK),
            ).verdict
            is not Verdict.MATCH
        ):
            continue
        link = cells[-1].css_first('a[href*="/playlists/"]')
        if link is not None and (href := link.attributes.get("href")):
            found[urljoin("https://wfmu.org", href)] = _date(text_of(link))
    return sorted(found.items(), key=lambda item: item[1] or "", reverse=True)
