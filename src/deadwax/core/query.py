import re
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
class _UrlRule:
    host: re.Pattern[str]
    path: re.Pattern[str]
    kind: EntityKind
    id_kind: IdKind | None = None


_MBID = r"(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
_BANDCAMP = re.compile(r"(?:^|\.)bandcamp\.com$")
_MUSICBRAINZ = re.compile(r"^musicbrainz\.org$")
_DISCOGS = re.compile(r"^discogs\.com$")
_SPOTIFY = re.compile(r"^open\.spotify\.com$")
_DEEZER = re.compile(r"^deezer\.com$")
_APPLE_MUSIC = re.compile(r"^music\.apple\.com$")
_SOUNDCLOUD = re.compile(r"^soundcloud\.com$")
_BEATPORT = re.compile(r"^beatport\.com$")

# A SoundCloud track page is '/<user>/<track>', optionally with a secret-link token; the
# names below are site sections and profile tabs, not users and tracks. Sets ('/<user>/sets/')
# are albums or playlists, which only the resolver can tell apart.
_SOUNDCLOUD_TRACK = re.compile(
    r"^/(?!(?:discover|search|charts|stream|you|upload|pages|settings|messages|notifications|"
    r"people|tags|terms-of-use)/)[^/]+/(?!(?:sets|likes|tracks|albums|reposts|followers|"
    r"following|popular-tracks|comments|spotlight)(?:/|$))[^/]+(?:/s-\w+)?/?$",
)

_URL_RULES = (
    _UrlRule(_SOUNDCLOUD, _SOUNDCLOUD_TRACK, EntityKind.TRACK),
    _UrlRule(
        _BEATPORT,
        re.compile(r"^(?:/[a-z]{2})?/track/[^/]+/(?P<id>\d+)"),
        EntityKind.TRACK,
        IdKind.BEATPORT_TRACK,
    ),
    _UrlRule(
        _BEATPORT,
        re.compile(r"^(?:/[a-z]{2})?/release/[^/]+/(?P<id>\d+)"),
        EntityKind.ALBUM,
        IdKind.BEATPORT_RELEASE,
    ),
    _UrlRule(_BANDCAMP, re.compile(r"^/album/"), EntityKind.ALBUM),
    _UrlRule(_BANDCAMP, re.compile(r"^/track/"), EntityKind.TRACK),
    _UrlRule(
        _MUSICBRAINZ,
        re.compile(rf"^/recording/{_MBID}"),
        EntityKind.TRACK,
        IdKind.MUSICBRAINZ_RECORDING,
    ),
    _UrlRule(
        _MUSICBRAINZ,
        re.compile(rf"^/release-group/{_MBID}"),
        EntityKind.ALBUM,
        IdKind.MUSICBRAINZ_RELEASE_GROUP,
    ),
    _UrlRule(
        _MUSICBRAINZ,
        re.compile(rf"^/release/{_MBID}"),
        EntityKind.ALBUM,
        IdKind.MUSICBRAINZ_RELEASE,
    ),
    _UrlRule(
        _DISCOGS,
        re.compile(r"^(?:/[^/]+)?/release/(?P<id>\d+)"),
        EntityKind.ALBUM,
        IdKind.DISCOGS_RELEASE,
    ),
    _UrlRule(
        _DISCOGS,
        re.compile(r"^(?:/[^/]+)?/master/(?P<id>\d+)"),
        EntityKind.ALBUM,
        IdKind.DISCOGS_MASTER,
    ),
    _UrlRule(
        _SPOTIFY,
        re.compile(r"^(?:/intl-[a-z]+)?/track/(?P<id>\w+)"),
        EntityKind.TRACK,
        IdKind.SPOTIFY,
    ),
    _UrlRule(
        _SPOTIFY,
        re.compile(r"^(?:/intl-[a-z]+)?/album/(?P<id>\w+)"),
        EntityKind.ALBUM,
        IdKind.SPOTIFY,
    ),
    _UrlRule(
        _DEEZER,
        re.compile(r"^(?:/[a-z]{2})?/track/(?P<id>\d+)"),
        EntityKind.TRACK,
        IdKind.DEEZER,
    ),
    _UrlRule(
        _DEEZER,
        re.compile(r"^(?:/[a-z]{2})?/album/(?P<id>\d+)"),
        EntityKind.ALBUM,
        IdKind.DEEZER,
    ),
    _UrlRule(
        _APPLE_MUSIC,
        re.compile(r"^/[a-z]{2}/song/(?:[^/]+/)?(?P<id>\d+)"),
        EntityKind.TRACK,
        IdKind.APPLE_MUSIC,
    ),
)

# Apple Music album URLs point at a track when they carry the `i` parameter.
_APPLE_ALBUM_PATH = re.compile(r"^/[a-z]{2}/album/(?:[^/]+/)?(?P<id>\d+)")

# Hyphen, non-breaking hyphen, figure dash, en and em dashes, horizontal bar, minus sign.
DASHES = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212"

# Straight, curly, low, and angle quotation marks.
QUOTES = "\"'\u201c\u201d\u2018\u2019\u00ab\u00bb\u201e"

_ARTIST_TITLE_SEPARATOR = re.compile(rf"\s+[{DASHES}]\s+")


def _host(netloc: str) -> str:
    host = netloc.lower().rsplit("@", 1)[-1].split(":", 1)[0]
    for prefix in ("www.", "m."):
        host = host.removeprefix(prefix)
    return host


def _apple_album(host: str, path: str, query: str) -> tuple[EntityKind, dict[IdKind, str]] | None:
    match = _APPLE_ALBUM_PATH.match(path) if _APPLE_MUSIC.match(host) else None
    if match is None:
        return None
    track_ids = parse_qs(query).get("i")
    if track_ids:
        return EntityKind.TRACK, {IdKind.APPLE_MUSIC: track_ids[0]}
    return EntityKind.ALBUM, {IdKind.APPLE_MUSIC: match["id"]}


def recognize_url(url: str) -> tuple[EntityKind | None, dict[IdKind, str]]:
    """Infer the record kind and identifiers from a known service URL."""
    parts = urlsplit(url)
    host, path = _host(parts.netloc), parts.path or "/"
    apple = _apple_album(host, path, parts.query)
    if apple is not None:
        return apple
    for rule in _URL_RULES:
        match = rule.path.match(path) if rule.host.search(host) else None
        if match is not None:
            ids = {rule.id_kind: match["id"]} if rule.id_kind is not None else {}
            return rule.kind, ids
    return None, {}


def _url_query(url: str, kind: EntityKind | None) -> Query:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise InvalidQueryError(f"not an HTTP(S) URL: {url}")
    url_kind, ids = recognize_url(url)
    if kind is not None and url_kind is not None and kind != url_kind:
        raise InvalidQueryError(f"the URL points to a {url_kind}, but a {kind} was requested")
    return Query(kind=kind or url_kind, url=url, ids=ids)


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


def parse_query(text: str, kind: EntityKind | None = None) -> Query:
    """Build a query from 'Artist - Title' text or a record page URL."""
    text = text.strip()
    if not text:
        raise InvalidQueryError("the query is empty")
    if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.IGNORECASE):
        return _url_query(text, kind)
    artist, title = _split_artist_title(text)
    if kind is None:
        raise InvalidQueryError("state whether the query is an album or a track")
    return Query(kind=kind, artist=artist, title=title)
