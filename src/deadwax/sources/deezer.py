from pydantic import BaseModel, ConfigDict

from deadwax.core import (
    CandidateLabel,
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
    RateLimitedError,
    RecordCandidate,
    RecordKey,
    Scope,
    SourceError,
    SourceGroup,
    Tag,
    TagKind,
    Verdict,
    compare,
)
from deadwax.sources._base import HttpAdapter, search_key

API = "https://api.deezer.com/"
_SEARCH_LIMIT = "25"

# Error codes Deezer returns in the body of an HTTP 200 response.
_NO_DATA = 800
_QUOTA = 4


class _Api(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class ErrorBody(_Api):
    """Error reported inside a successful HTTP response."""

    type: str = ""
    message: str = ""
    code: int = 0


class Envelope(_Api):
    """Any response, checked for an error first."""

    error: ErrorBody | None = None


class Named(_Api):
    """Artist, genre, or album reference."""

    id: int | None = None
    name: str | None = None
    title: str | None = None
    link: str | None = None


class Genres(_Api):
    """Genre list of an album."""

    data: list[Named] = []


class Track(_Api):
    """Track from a lookup or a search."""

    id: int
    title: str
    isrc: str | None = None
    link: str | None = None
    preview: str | None = None
    release_date: str | None = None
    artist: Named
    album: Named | None = None


class Album(_Api):
    """Album from a lookup or a search."""

    id: int
    title: str
    upc: str | None = None
    link: str | None = None
    label: str | None = None
    release_date: str | None = None
    artist: Named
    genres: Genres = Genres()


class TrackSearch(_Api):
    """Result of a track search."""

    data: list[Track] = []


class AlbumSearch(_Api):
    """Result of an album search."""

    data: list[Album] = []


def check(content: bytes, url: str) -> None:
    """Raise for an error Deezer reports inside an HTTP 200 response."""
    error = Envelope.model_validate_json(content).error
    if error is None:
        return
    if error.code == _NO_DATA:
        raise NotFoundError(error.message or "no data", url=url)
    if error.code == _QUOTA:
        raise RateLimitedError(error.message or "quota exceeded", url=url)
    raise SourceError(f"{error.type}: {error.message}", url=url)


def quoted(text: str) -> str:
    """Quote a value for Deezer's advanced search syntax."""
    return '"' + text.replace('"', " ") + '"'


def track_partial(track: Track) -> Partial:
    """Describe a track with its Deezer, album and artist links."""
    sources = [Provenance(source=DeezerAdapter.name, url=track.link)]

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
        source=DeezerAdapter.name,
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
    sources = [Provenance(source=DeezerAdapter.name, url=album.link)]

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
        source=DeezerAdapter.name,
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


def _matches(reference: RecordKey, artist: str | None, title: str, kind: EntityKind) -> bool:
    candidate = RecordKey(artist or "", title, kind)
    return compare(reference, candidate).verdict is Verdict.MATCH


class DeezerAdapter(HttpAdapter):
    """Deezer links, previews, ISRCs and barcodes from the keyless Deezer API."""

    name = "deezer"
    pass_ = Pass.ENRICH
    group = SourceGroup.CORE
    capabilities = frozenset({Capability.IDENTITY, Capability.LINKS, Capability.TAGS})

    def resolves(self, query: Query) -> bool:
        """Deezer URLs."""
        return IdKind.DEEZER in query.ids

    async def _get[M: _Api](self, model: type[M], path: str, **params: str) -> M:
        response = await self.client.get(f"{API}{path}", params=params)
        check(response.content, response.url)
        return model.model_validate_json(response.content)

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Look up by Deezer ID, then ISRC or barcode from earlier passes, then search."""
        key = search_key(query, context)
        kind = (key.kind if key is not None else None) or query.kind or EntityKind.TRACK

        if deezer_id := query.ids.get(IdKind.DEEZER):
            if kind is EntityKind.ALBUM:
                return album_partial(await self._get(Album, f"album/{deezer_id}"))
            return track_partial(await self._get(Track, f"track/{deezer_id}"))
        if kind is EntityKind.TRACK and context.identity.isrcs:
            isrc = context.identity.isrcs[0].value
            return track_partial(await self._get(Track, f"track/isrc:{isrc}"))
        if kind is EntityKind.ALBUM and context.identity.upcs:
            upc = context.identity.upcs[0].value
            return album_partial(await self._get(Album, f"album/upc:{upc}"))

        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        return await self._search(key, kind)

    async def _search(self, key: RecordKey, kind: EntityKind) -> Partial:
        if kind is EntityKind.ALBUM:
            q = f"artist:{quoted(key.artist)} album:{quoted(key.title)}"
            albums = await self._get(AlbumSearch, "search/album", q=q, limit=_SEARCH_LIMIT)
            album = next(
                (a for a in albums.data if _matches(key, a.artist.name, a.title, kind)),
                None,
            )
            if album is None:
                raise NotFoundError("no matching Deezer album")
            return album_partial(await self._get(Album, f"album/{album.id}"))

        q = f"artist:{quoted(key.artist)} track:{quoted(key.title)}"
        tracks = await self._get(TrackSearch, "search/track", q=q, limit=_SEARCH_LIMIT)
        track = next((t for t in tracks.data if _matches(key, t.artist.name, t.title, kind)), None)
        if track is None:
            raise NotFoundError("no matching Deezer track")
        return track_partial(await self._get(Track, f"track/{track.id}"))
