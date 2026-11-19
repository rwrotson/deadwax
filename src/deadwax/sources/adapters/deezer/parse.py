import json
import re
from typing import cast

from deadwax.core import (
    CandidateLabel,
    EntityKind,
    IdKind,
    Link,
    LinkTarget,
    Partial,
    Provenance,
    RecordCandidate,
    RecordKey,
    Scope,
    Tag,
    TagKind,
    Verdict,
    compare,
)
from deadwax.sources._html import json_ld, parse_html
from deadwax.sources.adapters.deezer.models import Album, Genres, Named, Track

SITE = "https://www.deezer.com"
SOURCE = "deezer"
_STATE = re.compile(r"window\.__DZR_APP_STATE__\s*=\s*")
PATH = re.compile(r"^/(?:[a-z]{2}/)?(album|track)/(\d+)(?:/|$)")
MAX_CANDIDATES = 10


def track_partial(track: Track) -> Partial:
    """Describe a track with its Deezer, album and artist links."""
    sources = [Provenance(source=SOURCE, url=track.link)]

    links = []
    if track.link:
        links.append(
            Link(
                service="deezer",
                url=track.link,
                target=LinkTarget.TRACK,
                preview_url=track.preview or None,
                sources=sources,
            ),
        )
    if track.album is not None and track.album.link:
        links.append(
            Link(service="deezer", url=track.album.link, target=LinkTarget.ALBUM, sources=sources),
        )
    if track.artist.link:
        links.append(
            Link(
                service="deezer",
                url=track.artist.link,
                target=LinkTarget.ARTIST,
                sources=sources,
            ),
        )

    return Partial(
        source=SOURCE,
        candidate=RecordCandidate(
            kind=EntityKind.TRACK,
            artist=track.artist.name or "",
            title=track.title,
            date=track.release_date,
            isrcs=[track.isrc] if track.isrc else [],
            ids={IdKind.DEEZER: str(track.id)},
            url=track.link,
        ),
        links=links,
    )


def album_partial(album: Album) -> Partial:
    """Describe an album with its label, barcode, genres and links."""
    sources = [Provenance(source=SOURCE, url=album.link)]

    links = []
    if album.link:
        links.append(
            Link(service="deezer", url=album.link, target=LinkTarget.ALBUM, sources=sources),
        )
    if album.artist.link:
        links.append(
            Link(
                service="deezer",
                url=album.artist.link,
                target=LinkTarget.ARTIST,
                sources=sources,
            ),
        )

    tags = [
        Tag(name=genre.name, kind=TagKind.GENRE, scope=Scope.RELEASE, sources=sources)
        for genre in album.genres.data
        if genre.name
    ]

    return Partial(
        source=SOURCE,
        candidate=RecordCandidate(
            kind=EntityKind.ALBUM,
            artist=album.artist.name or "",
            title=album.title,
            date=album.release_date,
            labels=[CandidateLabel(name=album.label)] if album.label else [],
            upcs=[album.upc] if album.upc else [],
            ids={IdKind.DEEZER: str(album.id)},
            url=album.link,
        ),
        tags=tags,
        links=links,
    )


def matches(reference: RecordKey, artist: str | None, title: str, kind: EntityKind) -> bool:
    """Whether a listed record is the one searched for."""
    candidate = RecordKey(artist or "", title, kind)
    return compare(reference, candidate).verdict is Verdict.MATCH


def page_data(content: bytes, kind: EntityKind) -> dict[str, object] | None:
    """Read the album or track state embedded in a Deezer page."""
    document = parse_html(content)
    for script in document.css("script"):
        text = script.text()
        if marker := _STATE.search(text):
            try:
                state, _ = json.JSONDecoder().raw_decode(text[marker.end() :].lstrip())
            except ValueError:
                continue
            if isinstance(state, dict) and isinstance(state.get("DATA"), dict):
                return cast(dict[str, object], state["DATA"])
    schema = "MusicAlbum" if kind is EntityKind.ALBUM else "MusicRecording"
    return next(iter(json_ld(document, schema)), None)


def _value(data: dict[str, object], *names: str) -> str | None:
    for name in names:
        value = data.get(name)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    return None


def _artist(data: dict[str, object]) -> Named:
    raw = data.get("byArtist")
    artist = raw if isinstance(raw, dict) else {}
    artist_id = _value(data, "ART_ID")
    return Named(
        name=_value(data, "ART_NAME") or _value(artist, "name"),
        link=f"{SITE}/artist/{artist_id}" if artist_id else None,
    )


def album_from_state(data: dict[str, object], item_id: str, url: str) -> Album:
    """Build an album from the page state."""
    genres = data.get("GENRES")
    genre_items = genres.get("data", []) if isinstance(genres, dict) else []
    names = [Named(name=item.get("name")) for item in genre_items if isinstance(item, dict)]
    return Album(
        id=int(item_id),
        title=_value(data, "ALB_TITLE", "name") or "",
        upc=_value(data, "UPC"),
        link=url,
        label=_value(data, "LABEL_NAME"),
        release_date=_value(data, "DIGITAL_RELEASE_DATE", "datePublished"),
        artist=_artist(data),
        genres=Genres(data=names),
    )


def track_from_state(data: dict[str, object], item_id: str, url: str) -> Track:
    """Build a track from the page state."""
    album_id = _value(data, "ALB_ID")
    return Track(
        id=int(item_id),
        title=_value(data, "SNG_TITLE", "name") or "",
        isrc=_value(data, "ISRC"),
        link=url,
        release_date=_value(data, "DIGITAL_RELEASE_DATE", "datePublished"),
        artist=_artist(data),
        album=Named(
            id=int(album_id) if album_id and album_id.isdigit() else None,
            title=_value(data, "ALB_TITLE"),
            link=f"{SITE}/album/{album_id}" if album_id else None,
        )
        if album_id
        else None,
    )
