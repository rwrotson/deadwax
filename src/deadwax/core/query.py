import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Self
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from deadwax.core.errors import InvalidQueryError


class EntityKind(StrEnum):
    """Kind of record a query asks about."""

    TRACK = "track"
    ALBUM = "album"


class IdKind(StrEnum):
    """Namespace of an external identifier."""

    MUSICBRAINZ_RECORDING = "musicbrainz_recording"
    MUSICBRAINZ_RELEASE = "musicbrainz_release"
    MUSICBRAINZ_RELEASE_GROUP = "musicbrainz_release_group"
    MUSICBRAINZ_ARTIST = "musicbrainz_artist"
    MUSICBRAINZ_WORK = "musicbrainz_work"
    MUSICBRAINZ_LABEL = "musicbrainz_label"
    DISCOGS_RELEASE = "discogs_release"
    DISCOGS_MASTER = "discogs_master"
    DISCOGS_ARTIST = "discogs_artist"
    DISCOGS_LABEL = "discogs_label"
    WIKIDATA = "wikidata"
    BANDCAMP_ALBUM = "bandcamp_album"
    BANDCAMP_TRACK = "bandcamp_track"
    SPOTIFY = "spotify"
    APPLE_MUSIC = "apple_music"
    DEEZER = "deezer"
    SOUNDCLOUD = "soundcloud"
    BEATPORT_TRACK = "beatport_track"
    BEATPORT_RELEASE = "beatport_release"


class Query(BaseModel):
    """What to look up: artist and title of a track or album, or a URL of a record page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EntityKind | None = Field(
        default=None,
        description="Track or album; a URL query may leave it to the resolver",
    )
    artist: str | None = None
    title: str | None = None
    url: str | None = None
    ids: dict[IdKind, str] = Field(
        default_factory=dict,
        description="Identifiers recognized in the URL",
    )

    @model_validator(mode="after")
    def _require_target(self) -> Self:
        if self.url is None:
            if not (self.artist and self.title):
                raise ValueError("a query needs an artist and a title, or a URL")
            if self.kind is None:
                raise ValueError("a text query must state whether it is an album or a track")
        return self


@dataclass(frozen=True, slots=True)
class UrlRule:
    """Path of a record page on one service, the kind of record it opens, and its identifier.

    The identifier is the path's `id` group, or the value of `param` when it is set; a rule
    with `param` matches only URLs that carry that query parameter.
    """

    path: re.Pattern[str]
    kind: EntityKind
    id_kind: IdKind | None = None
    param: str | None = None


# Hyphen, non-breaking hyphen, figure dash, en and em dashes, horizontal bar, minus sign.
DASHES = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212"

# Straight, curly, low, and angle quotation marks.
QUOTES = "\"'\u201c\u201d\u2018\u2019\u00ab\u00bb\u201e"

_ARTIST_TITLE_SEPARATOR = re.compile(rf"\s+[{DASHES}]\s+")


def recognize_url(
    url: str,
    rules: Iterable[UrlRule],
) -> tuple[EntityKind | None, dict[IdKind, str]]:
    """Infer the record kind and identifiers of a URL from the first rule its path matches."""
    parts = urlsplit(url)
    path = parts.path or "/"
    params = parse_qs(parts.query)
    for rule in rules:
        match = rule.path.match(path)
        values = params.get(rule.param) if rule.param is not None else None
        if match is None or (rule.param is not None and not values):
            continue
        if rule.id_kind is None:
            return rule.kind, {}
        return rule.kind, {rule.id_kind: values[0] if values else match["id"]}
    return None, {}


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) > 1 and text[0] in QUOTES and text[-1] in QUOTES:
        text = text[1:-1].strip()
    return text


def _split_artist_title(text: str) -> tuple[str, str]:
    match _ARTIST_TITLE_SEPARATOR.split(_unquote(text), maxsplit=1):
        case [artist, title]:
            artist, title = _unquote(artist), _unquote(title)
        case _:
            raise InvalidQueryError(f"expected 'Artist - Title', got {text!r}")
    if not artist or not title:
        raise InvalidQueryError(f"expected 'Artist - Title', got {text!r}")
    return artist, title


def text_query(text: str, kind: EntityKind | None) -> Query:
    """Build a query from 'Artist - Title' text."""
    text = text.strip()
    if not text:
        raise InvalidQueryError("the query is empty")
    artist, title = _split_artist_title(text)
    if kind is None:
        raise InvalidQueryError("state whether the query is an album or a track")
    return Query(kind=kind, artist=artist, title=title)
