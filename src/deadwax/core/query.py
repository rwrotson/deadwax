import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, Self, assert_never
from urllib.parse import parse_qs, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    field_validator,
    model_validator,
)

from deadwax.core.errors import InvalidQueryError


class EntityKind(StrEnum):
    """Kind of record a query asks about."""

    TRACK = "track"
    ALBUM = "album"
    ARTIST = "artist"
    LABEL = "label"


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
    BEATPORT_ARTIST = "beatport_artist"
    BEATPORT_LABEL = "beatport_label"
    ISRC = "isrc"


# Tag of the query, identity, or candidate variant whose kind is not known.
UNRESOLVED = "unresolved"


def _isrc_misfit(kind: EntityKind | None) -> str:
    article = "an" if str(kind)[0] in "aeiou" else "a"
    return f"an ISRC identifies a track, not {article} {kind}"


class _QueryBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EntityKind | None = None
    url: str | None = None
    ids: dict[IdKind, str] = Field(
        default_factory=dict,
        description="Identifiers recognized in the URL, and an ISRC the caller knows",
    )

    @field_validator("ids")
    @classmethod
    def _normalize_isrc(cls, ids: dict[IdKind, str]) -> dict[IdKind, str]:
        if IdKind.ISRC in ids:
            return ids | {IdKind.ISRC: isrc_code(ids[IdKind.ISRC])}
        return ids

    def _forbid_isrc(self) -> None:
        if IdKind.ISRC in self.ids:
            raise ValueError(_isrc_misfit(self.kind))


class _RecordQuery(_QueryBase):
    artist: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def _require_target(self) -> Self:
        if self.url is None and not (self.artist and self.title):
            raise ValueError("a query needs an artist and a title, or a URL")
        return self


class TrackQuery(_RecordQuery):
    """Track named by artist and title, or the URL of its page."""

    kind: Literal[EntityKind.TRACK] = EntityKind.TRACK


class AlbumQuery(_RecordQuery):
    """Album named by artist and title, or the URL of its page."""

    kind: Literal[EntityKind.ALBUM] = EntityKind.ALBUM

    @model_validator(mode="after")
    def _check_ids(self) -> Self:
        self._forbid_isrc()
        return self


class _NameQuery(_QueryBase):
    name: str | None = None

    @model_validator(mode="after")
    def _require_target(self) -> Self:
        if self.url is None and not self.name:
            raise ValueError("a query needs a name or a URL")
        self._forbid_isrc()
        return self


class ArtistQuery(_NameQuery):
    """Artist named by name, or the URL of their page."""

    kind: Literal[EntityKind.ARTIST] = EntityKind.ARTIST


class LabelQuery(_NameQuery):
    """Label named by name, or the URL of its page."""

    kind: Literal[EntityKind.LABEL] = EntityKind.LABEL


class UnresolvedQuery(_QueryBase):
    """URL of a page whose record kind only the resolving source can tell."""

    kind: None = None
    url: str


def kind_tag(value: object) -> str:
    """Name the variant of a query, identity, or candidate by its kind, given as model or JSON."""
    kind = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    return UNRESOLVED if kind is None else str(kind)


type RecordQuery = TrackQuery | AlbumQuery
type NameQuery = ArtistQuery | LabelQuery

type Query = Annotated[
    Annotated[TrackQuery, Tag(EntityKind.TRACK)]
    | Annotated[AlbumQuery, Tag(EntityKind.ALBUM)]
    | Annotated[ArtistQuery, Tag(EntityKind.ARTIST)]
    | Annotated[LabelQuery, Tag(EntityKind.LABEL)]
    | Annotated[UnresolvedQuery, Tag(UNRESOLVED)],
    Discriminator(kind_tag),
]

_QUERIES: dict[EntityKind, type[TrackQuery | AlbumQuery | ArtistQuery | LabelQuery]] = {
    EntityKind.TRACK: TrackQuery,
    EntityKind.ALBUM: AlbumQuery,
    EntityKind.ARTIST: ArtistQuery,
    EntityKind.LABEL: LabelQuery,
}


def with_kind(query: Query, kind: EntityKind | None) -> Query:
    """Turn a query of unknown kind into the query of a kind found later, keeping URL and ids."""
    if not isinstance(query, UnresolvedQuery) or kind is None:
        return query
    ids = query.ids

    # A resolver may find that an ISRC given with the URL does not fit the record.
    if kind is not EntityKind.TRACK:
        ids = {id_kind: value for id_kind, value in ids.items() if id_kind is not IdKind.ISRC}

    return _QUERIES[kind](url=query.url, ids=ids)


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

# Country, registrant, year, and designation code.
_ISRC = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")


def normalize_code(code: str) -> str:
    """Normalize an ISRC or catalog number: uppercase without spaces, dots, or hyphens."""
    return re.sub(r"[\s.\-]", "", unicodedata.normalize("NFKC", code)).upper()


def isrc_code(code: str) -> str:
    """Normalize an ISRC and check its form; a malformed one is an `InvalidQueryError`."""
    normalized = normalize_code(code)
    if _ISRC.match(normalized) is None:
        raise InvalidQueryError(f"not an ISRC: {code!r}")
    return normalized


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


def isrc_ids(isrc: str | None, kind: EntityKind | None) -> dict[IdKind, str]:
    """Identifiers of a query from an ISRC the caller gives, checked against the query kind."""
    if isrc is None:
        return {}
    if kind not in {EntityKind.TRACK, None}:
        raise InvalidQueryError(_isrc_misfit(kind))
    return {IdKind.ISRC: isrc_code(isrc)}


def url_query(url: str, kind: EntityKind | None, ids: dict[IdKind, str]) -> Query:
    """Build the query of a record page URL, of a known kind or left to the resolver."""
    if kind is None:
        return UnresolvedQuery(url=url, ids=ids)
    return _QUERIES[kind](url=url, ids=ids)


def text_query(text: str, kind: EntityKind | None, *, isrc: str | None = None) -> Query:
    """Build a query from 'Artist - Title' text or a name and, optionally, the track's ISRC."""
    text = text.strip()
    if not text:
        raise InvalidQueryError("the query is empty")
    if kind is None:
        raise InvalidQueryError("state whether the query is a track, album, artist, or label")
    ids = isrc_ids(isrc, kind)
    match kind:
        case EntityKind.ARTIST | EntityKind.LABEL:
            name = _unquote(text)
            if not name:
                raise InvalidQueryError("the query is empty")
            return ArtistQuery(name=name) if kind is EntityKind.ARTIST else LabelQuery(name=name)
        case EntityKind.TRACK:
            artist, title = _split_artist_title(text)
            return TrackQuery(artist=artist, title=title, ids=ids)
        case EntityKind.ALBUM:
            artist, title = _split_artist_title(text)
            return AlbumQuery(artist=artist, title=title)
        case _:
            assert_never(kind)
