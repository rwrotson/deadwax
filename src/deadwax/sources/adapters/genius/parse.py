from deadwax.core import (
    EntityKind,
    RecordCandidate,
)
from deadwax.sources._html import parse_html
from deadwax.sources.adapters.genius.models import RichText, Song

API = "https://api.genius.com"
MAX_ANNOTATION_PAGES = 3


def plain_text(value: RichText) -> str:
    """Plain-text rendering of a Genius rich-text field."""
    return (value.plain or "").strip()


def candidate(song: Song) -> RecordCandidate | None:
    """Describe a Genius song as a record candidate."""
    artist = song.primary_artist.name
    if song.title is None or not artist:
        return None
    return RecordCandidate(
        kind=EntityKind.TRACK,
        artist=artist,
        title=song.title,
        url=song.url or "",
    )


def lyrics(content: bytes) -> str:
    """Lyrics shown on a Genius song page."""
    tree = parse_html(content)
    containers = tree.css('[data-lyrics-container="true"]')
    lines = [container.text(separator="\n", strip=True) for container in containers]
    return "\n".join(line for line in lines if line).strip()
