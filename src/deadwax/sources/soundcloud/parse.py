import re

from deadwax.core import Entity as RelatedEntity
from deadwax.core import (
    EntityKind,
    EntityType,
    IdKind,
    Link,
    LinkTarget,
    Metric,
    MetricKind,
    Partial,
    Provenance,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    Tag,
    TagKind,
    Text,
    TextKind,
    normalize_artist,
)
from deadwax.sources._base import SearchHit
from deadwax.sources.soundcloud import models

SOURCE = "soundcloud"
SERVICE = "soundcloud"
PUBLICATION = "SoundCloud"

# Set types SoundCloud gives releases, as opposed to listeners' playlists.
ALBUM_SET_TYPES = frozenset({"album", "ep", "single", "compilation"})

# Uploads often title a track "Artist - Title".
_ARTIST_TITLE = re.compile(r"\s+[-\u2013\u2014]\s+")

# Tags are separated by spaces; a tag with spaces is quoted.
_TAG = re.compile(r'"([^"]+)"|(\S+)')

# Reposters with fewer followers are mostly listeners rather than artists, labels, or DJs.
NOTABLE_FOLLOWERS = 1000

_MARKED = re.compile(r"^\s*(?:℗|©|\([PpCc]\))")


def record_key(item: models.Item, kind: EntityKind) -> RecordKey:
    """Artist and title an upload names.

    The distributor's artist comes first; otherwise a 'Artist - Title' title, else the uploader.
    """
    artist = item.publisher_metadata.artist if item.publisher_metadata is not None else None
    title = item.title.strip()
    parts = _ARTIST_TITLE.split(title, maxsplit=1)
    if artist:
        if len(parts) == 2 and parts[0].casefold() == artist.casefold():  # noqa: PLR2004
            title = parts[1]
    elif len(parts) == 2:  # noqa: PLR2004 -- artist and title
        artist, title = parts
    else:
        artist = item.user.username if item.user is not None else ""
    return RecordKey(artist=artist, title=title, kind=kind)


def _official_rank(item: models.Item, artist: str) -> int:
    """0 for an upload with distributor metadata, 1 by an account named like the artist, else 2."""
    metadata = item.publisher_metadata
    if metadata is not None and (metadata.artist or metadata.isrc or metadata.upc_or_ean):
        return 0
    if item.user is not None and normalize_artist(item.user.username) == normalize_artist(artist):
        return 1
    return 2


def _hits(items: list[models.Item], kind: EntityKind, artist: str) -> list[SearchHit]:
    """Hits of uploads with a page, official uploads first: listeners re-upload records too."""
    ranked = sorted(
        (item for item in items if item.permalink_url),
        key=lambda item: _official_rank(item, artist),
    )
    return [
        SearchHit(url=item.permalink_url, key=record_key(item, kind))
        for item in ranked
        if item.permalink_url
    ]


def track_hits(results: models.TrackSearch, artist: str) -> list[SearchHit]:
    """Track search results as hits pointing at their pages, official uploads first."""
    return _hits(list(results.collection), EntityKind.TRACK, artist)


def album_hits(results: models.PlaylistSearch, artist: str) -> list[SearchHit]:
    """Album search results as hits, official ones first; listeners' playlists are left out."""
    releases = [
        playlist for playlist in results.collection if (playlist.set_type or "") in ALBUM_SET_TYPES
    ]
    return _hits(list(releases), EntityKind.ALBUM, artist)


def _copyright(text: str | None, mark: str) -> list[str]:
    if text is None or not text.strip():
        return []
    text = text.strip()
    return [text if _MARKED.match(text) else f"{mark} {text}"]


def candidate(item: models.Item, kind: EntityKind) -> RecordCandidate:
    """Describe the record an upload names, with the distributor's codes when given."""
    key = record_key(item, kind)
    metadata = item.publisher_metadata or models.PublisherMetadata()
    # Only the release date: the upload date of a re-upload says nothing about the record.
    date = item.release_date
    return RecordCandidate(
        kind=kind,
        artist=key.artist,
        title=key.title,
        date=date[:10] if date else None,
        isrcs=[metadata.isrc] if metadata.isrc and kind is EntityKind.TRACK else [],
        upcs=[metadata.upc_or_ean] if metadata.upc_or_ean and kind is EntityKind.ALBUM else [],
        copyrights=_copyright(metadata.p_line, "℗") + _copyright(metadata.c_line, "©"),
        ids={IdKind.SOUNDCLOUD: str(item.id)},
        url=item.permalink_url,
    )


def tags(item: models.Item, scope: Scope, sources: list[Provenance]) -> list[Tag]:
    """The uploader's genre and free tags."""
    result = []
    if item.genre and item.genre.strip():
        genre = Tag(name=item.genre.strip(), kind=TagKind.GENRE, scope=scope, sources=sources)
        result.append(genre)
    names = [quoted or bare for quoted, bare in _TAG.findall(item.tag_list or "")]
    seen = {item.genre.strip().casefold()} if item.genre else set()
    for name in names:
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        result.append(Tag(name=name, kind=TagKind.TAG, scope=scope, sources=sources))
    return result


def description(item: models.Item, scope: Scope, sources: list[Provenance]) -> list[Text]:
    """The uploader's description, as the words of whoever published the record."""
    if item.description is None or not item.description.strip():
        return []
    return [
        Text(
            kind=TextKind.LABEL,
            body=item.description.strip(),
            author=item.user.username if item.user is not None else None,
            publication=PUBLICATION,
            scope=scope,
            sources=sources,
        ),
    ]


def metrics(item: models.Item, scope: Scope, sources: list[Provenance]) -> list[Metric]:
    """Plays, likes, and reposts of the upload."""
    plays = item.playback_count if isinstance(item, models.Track) else None
    counts = (
        (MetricKind.LISTENS, plays),
        (MetricKind.LIKES, item.likes_count),
        (MetricKind.REPOSTS, item.reposts_count),
    )
    return [
        Metric(kind=kind, value=value, scope=scope, sources=sources)
        for kind, value in counts
        if value is not None
    ]


def reposters(users: models.Users, scope: Scope, sources: list[Provenance]) -> list[Relation]:
    """Notable accounts that reposted the upload: artists, labels, and DJs vouching for it.

    An account counts when it is verified or has `NOTABLE_FOLLOWERS` followers.
    """
    return [
        Relation(
            kind=RelationKind.REPOSTED_BY,
            target=RelatedEntity(
                type=EntityType.ARTIST,
                name=user.username,
                url=user.permalink_url,
            ),
            scope=scope,
            sources=sources,
        )
        for user in users.collection
        if user.verified or user.followers_count >= NOTABLE_FOLLOWERS
    ]


def partial(item: models.Item, kind: EntityKind, reposted_by: models.Users) -> Partial:
    """Everything an upload tells about the record."""
    scope = Scope.RECORDING if kind is EntityKind.TRACK else Scope.RELEASE
    sources = [Provenance(source=SOURCE, url=item.permalink_url)]
    record = candidate(item, kind)

    links = []
    if item.permalink_url:
        target = LinkTarget.TRACK if kind is EntityKind.TRACK else LinkTarget.ALBUM
        links.append(Link(service=SERVICE, url=item.permalink_url, target=target, sources=sources))
    if item.user is not None and item.user.permalink_url:
        # The uploader is the artist or someone else, such as the label.
        is_artist = normalize_artist(item.user.username) == normalize_artist(record.artist)
        links.append(
            Link(
                service=SERVICE,
                url=item.user.permalink_url,
                target=LinkTarget.ARTIST if is_artist else LinkTarget.OTHER,
                sources=sources,
            ),
        )

    return Partial(
        source=SOURCE,
        candidate=record,
        tags=tags(item, scope, sources),
        texts=description(item, scope, sources),
        relations=reposters(reposted_by, scope, sources),
        metrics=metrics(item, scope, sources),
        links=links,
    )
