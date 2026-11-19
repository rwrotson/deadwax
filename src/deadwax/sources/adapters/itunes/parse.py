from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from deadwax.core import (
    EntityKind,
    IdKind,
    Link,
    LinkTarget,
    LookupContext,
    Partial,
    Provenance,
    Query,
    RecordCandidate,
    RecordKey,
    Scope,
    Tag,
    TagKind,
    Verdict,
    compare,
)
from deadwax.sources.adapters.itunes.models import Item
from deadwax.sources.services import recognize

SOURCE = "itunes"
API = "https://itunes.apple.com/"
SERVICE = "apple_music"
SEARCH_LIMIT = "25"


def clean_url(url: str, *, album: bool = False) -> str:
    """Drop the affiliate parameter iTunes adds, and for an album link the track parameter."""
    dropped = {"uo", "i"} if album else {"uo"}
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in dropped]
    return urlunsplit(parts._replace(query=urlencode(query)))


def pick(reference: RecordKey, items: list[Item]) -> Item | None:
    """Return the earliest release among the items that match the reference."""
    matching = [
        item
        for item in items
        if item.kind is reference.kind
        and compare(reference, RecordKey(item.artist_name, item.title, item.kind)).verdict
        is Verdict.MATCH
    ]
    return min(matching, key=lambda item: item.release_date or "9999", default=None)


def partial(item: Item) -> Partial:
    """Describe a track or album with its store, album, artist and preview links."""
    kind = item.kind or EntityKind.TRACK
    if kind is EntityKind.TRACK:
        own_url, own_id, target = item.track_view_url, item.track_id, LinkTarget.TRACK
    else:
        own_url, own_id, target = item.collection_view_url, item.collection_id, LinkTarget.ALBUM

    url = clean_url(own_url) if own_url else None
    sources = [Provenance(source=SOURCE, url=url)]

    links = []
    if url is not None:
        links.append(
            Link(
                service=SERVICE,
                url=url,
                target=target,
                preview_url=item.preview_url,
                sources=sources,
            ),
        )
    if kind is EntityKind.TRACK and item.collection_view_url:
        album_url = clean_url(item.collection_view_url, album=True)
        links.append(Link(service=SERVICE, url=album_url, target=LinkTarget.ALBUM, sources=sources))
    if item.artist_view_url:
        artist_url = clean_url(item.artist_view_url)
        links.append(
            Link(service=SERVICE, url=artist_url, target=LinkTarget.ARTIST, sources=sources),
        )

    tags = []
    if item.primary_genre_name:
        tags.append(
            Tag(
                name=item.primary_genre_name,
                kind=TagKind.GENRE,
                scope=Scope.RELEASE,
                sources=sources,
            ),
        )

    return Partial(
        source=SOURCE,
        candidate=RecordCandidate(
            kind=kind,
            artist=item.artist_name,
            title=item.title,
            date=item.release_date[:10] if item.release_date else None,
            ids={IdKind.APPLE_MUSIC: str(own_id)} if own_id is not None else {},
            url=url,
        ),
        tags=tags,
        links=links,
    )


def linked_id(query: Query, context: LookupContext) -> str | None:
    """Apple Music ID of the record from a link an earlier source curated, such as MusicBrainz."""
    kind = query.kind or context.identity.kind
    for url in context.urls(SERVICE):
        url_kind, ids = recognize(url)
        if url_kind is kind and IdKind.APPLE_MUSIC in ids:
            return ids[IdKind.APPLE_MUSIC]
    return None
