from collections.abc import Mapping

from deadwax.core import (
    EntityKind,
    RecordCandidate,
)
from deadwax.sources._html import parse_html

API = "https://api.genius.com"
MAX_ANNOTATION_PAGES = 3


def plain_text(value: object) -> str:
    """Plain-text rendering of a Genius rich-text field."""
    if not isinstance(value, Mapping):
        return ""
    plain = value.get("plain")
    return plain.strip() if isinstance(plain, str) else ""


def as_song(value: object) -> Mapping[str, object]:
    """The value as a JSON object, or an empty one."""
    return value if isinstance(value, Mapping) else {}


def as_list(value: object) -> list[object]:
    """The value as a JSON list, or an empty one."""
    return value if isinstance(value, list) else []


def name_of(value: object) -> str:
    """Name of a Genius artist object."""
    name = as_song(value).get("name")
    return name if isinstance(name, str) else ""


def url_of(song: Mapping[str, object]) -> str:
    """Page URL of a Genius song."""
    value = song.get("url")
    return value if isinstance(value, str) else ""


def candidate(song: Mapping[str, object]) -> RecordCandidate | None:
    """Describe a Genius song as a record candidate."""
    title = song.get("title")
    artist = name_of(song.get("primary_artist"))
    if not isinstance(title, str) or not artist:
        return None
    return RecordCandidate(kind=EntityKind.TRACK, artist=artist, title=title, url=url_of(song))


def lyrics(content: bytes) -> str:
    """Lyrics shown on a Genius song page."""
    tree = parse_html(content)
    containers = tree.css('[data-lyrics-container="true"]')
    lines = [container.text(separator="\n", strip=True) for container in containers]
    return "\n".join(line for line in lines if line).strip()
