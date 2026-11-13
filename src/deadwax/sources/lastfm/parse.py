import re
from collections.abc import Iterable
from datetime import datetime

from deadwax.core import (
    Entity,
    EntityKind,
    EntityType,
    NotFoundError,
    Provenance,
    RateLimitedError,
    RecordCandidate,
    Relation,
    RelationKind,
    Scope,
    SourceError,
    Tag,
    TagKind,
    Text,
    TextKind,
)
from deadwax.sources._html import parse_html
from deadwax.sources.lastfm import models

SOURCE = "lastfm"
PUBLICATION = "Last.fm"
TAGS_LIMIT = 25
ARTIST_TAGS_LIMIT = 10

# Error codes of the Last.fm API.
_NOT_FOUND = 6
_RATE_LIMITED = 29

_READ_MORE = re.compile(r"<a\b[^>]*>\s*Read more on Last\.fm\s*</a>\.?", re.IGNORECASE)
_LICENCE = re.compile(
    r"User-contributed text is available under the Creative Commons By-SA License;"
    r"\s*additional terms may apply\.?",
    re.IGNORECASE,
)
_PARAGRAPHS = re.compile(r"\n\s*\n")


def check(content: bytes, url: str) -> None:
    """Raise for an error Last.fm reports in the response body."""
    envelope = models.Envelope.model_validate_json(content)
    if envelope.error is None:
        return
    if envelope.error == _NOT_FOUND:
        raise NotFoundError(envelope.message or "not found", url=url)
    if envelope.error == _RATE_LIMITED:
        raise RateLimitedError(envelope.message or "rate limit exceeded", url=url)
    raise SourceError(f"error {envelope.error}: {envelope.message}", url=url)


def tags(
    found: Iterable[models.Tag],
    scope: Scope,
    url: str | None,
    limit: int = TAGS_LIMIT,
) -> list[Tag]:
    """Return the most used tags with their relative count as weight; unused tags are dropped."""
    sources = [Provenance(source=SOURCE, url=url)]
    result = []
    for tag in found:
        if tag.count <= 0 or not tag.name.strip():
            continue
        weight = min(tag.count, 100) / 100
        result.append(
            Tag(
                name=tag.name.strip(),
                kind=TagKind.TAG,
                weight=weight,
                scope=scope,
                sources=sources,
            ),
        )
    return result[:limit]


def wiki_body(wiki: models.Wiki) -> str | None:
    """Return the wiki text without markup, the 'Read more' link, and the licence notice."""
    html = _LICENCE.sub("", _READ_MORE.sub("", wiki.content or wiki.summary))
    text = parse_html(html).text()
    paragraphs = (" ".join(part.split()) for part in _PARAGRAPHS.split(text))
    body = "\n\n".join(part for part in paragraphs if part)
    return body or None


def published(value: str | None) -> str | None:
    """Convert '01 Jan 2009, 12:00' to an ISO date."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d %b %Y, %H:%M").date().isoformat()  # noqa: DTZ007 -- only the date is kept
    except ValueError:
        return None


def wiki_texts(wiki: models.Wiki | None, scope: Scope, url: str | None) -> list[Text]:
    """Return the wiki text of a track or album, if it has one."""
    if wiki is None:
        return []
    body = wiki_body(wiki)
    if body is None:
        return []
    return [
        Text(
            kind=TextKind.WIKI,
            body=body,
            publication=PUBLICATION,
            date=published(wiki.published),
            scope=scope,
            sources=[Provenance(source=SOURCE, url=url)],
        ),
    ]


def track_candidate(track: models.TrackInfo) -> RecordCandidate:
    """Describe a track; its version is derived from the title."""
    return RecordCandidate(
        kind=EntityKind.TRACK,
        artist=track.artist.name,
        title=track.name,
        url=track.url,
    )


def album_candidate(album: models.AlbumInfo) -> RecordCandidate:
    """Describe an album."""
    return RecordCandidate(
        kind=EntityKind.ALBUM,
        artist=album.artist,
        title=album.name,
        url=album.url,
    )


def _note(match: float | None) -> str | None:
    return f"match {match:.2f}" if match is not None else None


def similar_tracks(found: Iterable[models.SimilarTrack], url: str | None) -> list[Relation]:
    """Tracks listened to by the same people."""
    sources = [Provenance(source=SOURCE, url=url)]
    return [
        Relation(
            kind=RelationKind.SIMILAR,
            target=Entity(
                type=EntityType.RECORDING,
                name=track.name,
                artist=track.artist.name,
                url=track.url,
            ),
            note=_note(track.match),
            scope=Scope.RECORDING,
            sources=sources,
        )
        for track in found
    ]


def similar_artists(found: Iterable[models.SimilarArtist], url: str | None) -> list[Relation]:
    """Artists listened to by the same people."""
    sources = [Provenance(source=SOURCE, url=url)]
    return [
        Relation(
            kind=RelationKind.SIMILAR,
            target=Entity(type=EntityType.ARTIST, name=artist.name, url=artist.url),
            note=_note(artist.match),
            scope=Scope.ARTIST,
            sources=sources,
        )
        for artist in found
    ]
