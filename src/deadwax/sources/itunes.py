from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from deadwax.core import (
    Capability,
    EntityKind,
    IdKind,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RecordCandidate,
    RecordKey,
    Scope,
    SourceGroup,
    Tag,
    TagKind,
    Verdict,
    compare,
    recognize_url,
)
from deadwax.sources._base import HttpAdapter, search_key

API = "https://itunes.apple.com/"
SERVICE = "apple_music"
_SEARCH_LIMIT = "25"


class _Api(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Item(_Api):
    """Track or collection from the iTunes Search API."""

    wrapper_type: str = Field(alias="wrapperType")
    artist_name: str = Field(default="", alias="artistName")
    track_name: str | None = Field(default=None, alias="trackName")
    collection_name: str | None = Field(default=None, alias="collectionName")
    track_id: int | None = Field(default=None, alias="trackId")
    collection_id: int | None = Field(default=None, alias="collectionId")
    track_view_url: str | None = Field(default=None, alias="trackViewUrl")
    collection_view_url: str | None = Field(default=None, alias="collectionViewUrl")
    artist_view_url: str | None = Field(default=None, alias="artistViewUrl")
    preview_url: str | None = Field(default=None, alias="previewUrl")
    release_date: str | None = Field(default=None, alias="releaseDate")
    primary_genre_name: str | None = Field(default=None, alias="primaryGenreName")

    @property
    def kind(self) -> EntityKind | None:
        """Track or album, or None for artists and other results."""
        if self.wrapper_type == "track" and self.track_name is not None:
            return EntityKind.TRACK
        if self.wrapper_type == "collection" and self.collection_name is not None:
            return EntityKind.ALBUM
        return None

    @property
    def title(self) -> str:
        """Track title for tracks, collection title for albums."""
        if self.kind is EntityKind.TRACK and self.track_name is not None:
            return self.track_name
        return self.collection_name or ""


class Results(_Api):
    """Response of the search and lookup endpoints."""

    results: list[Item] = []


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
    sources = [Provenance(source=ItunesAdapter.name, url=url)]

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
        source=ItunesAdapter.name,
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


class ItunesAdapter(HttpAdapter):
    """Apple Music links and previews from the keyless iTunes Search API."""

    name = "itunes"
    pass_ = Pass.ENRICH
    group = SourceGroup.CORE
    capabilities = frozenset({Capability.IDENTITY, Capability.LINKS, Capability.TAGS})

    def resolves(self, query: Query) -> bool:
        """Apple Music URLs."""
        return IdKind.APPLE_MUSIC in query.ids

    async def _get(self, path: str, **params: str) -> list[Item]:
        response = await self.client.get(f"{API}{path}", params=params)
        return Results.model_validate_json(response.content).results

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Look up the Apple Music ID of the query, or search by artist and title."""
        apple_id = query.ids.get(IdKind.APPLE_MUSIC) or _linked_id(query, context)
        if apple_id is not None:
            items = [item for item in await self._get("lookup", id=apple_id) if item.kind]
            if not items:
                raise NotFoundError(f"no iTunes item {apple_id}")
            return partial(items[0])

        reference = search_key(query, context)
        if reference is None:
            raise NotFoundError("neither the query nor earlier sources name the record")

        kind = reference.kind or EntityKind.TRACK
        entity = "song" if kind is EntityKind.TRACK else "album"
        items = await self._get(
            "search",
            term=f"{reference.artist} {reference.title}",
            media="music",
            entity=entity,
            limit=_SEARCH_LIMIT,
        )

        item = pick(RecordKey(reference.artist, reference.title, kind, reference.version), items)
        if item is None:
            raise NotFoundError("no matching iTunes item")
        return partial(item)


def _linked_id(query: Query, context: LookupContext) -> str | None:
    """Apple Music ID of the record from a link an earlier source curated, such as MusicBrainz."""
    kind = query.kind or context.identity.kind
    for url in context.urls(SERVICE):
        url_kind, ids = recognize_url(url)
        if url_kind is kind and IdKind.APPLE_MUSIC in ids:
            return ids[IdKind.APPLE_MUSIC]
    return None
