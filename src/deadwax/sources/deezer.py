import json
import re
from typing import cast
from urllib.parse import quote, urljoin, urlsplit

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
from deadwax.sources._html import json_ld, parse_html
from deadwax.sources._http import Profile

SITE = "https://www.deezer.com"
_STATE = re.compile(r"window\.__DZR_APP_STATE__\s*=\s*")
_PATH = re.compile(r"^/(?:[a-z]{2}/)?(album|track)/(\d+)(?:/|$)")
_MAX_CANDIDATES = 10


class _Api(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


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
    """Deezer identity and listening links from public record pages."""

    name = "deezer"
    pass_ = Pass.ENRICH
    group = SourceGroup.CORE
    capabilities = frozenset({Capability.IDENTITY, Capability.LINKS, Capability.TAGS})
    profile = Profile.BROWSER

    def resolves(self, query: Query) -> bool:
        """Deezer URLs."""
        return IdKind.DEEZER in query.ids

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Read a Deezer URL or search public HTML for the requested record."""
        key = search_key(query, context)
        kind = (key.kind if key is not None else None) or query.kind or EntityKind.TRACK
        if query.url is not None and self.resolves(query):
            return await self._page(query.url, kind)
        known = next(
            (
                url
                for url in context.urls("deezer")
                if (match := _PATH.match(urlsplit(url).path)) is not None
                and match.group(1) == kind.value
            ),
            None,
        )
        if known is not None:
            return await self._page(known, kind)
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        return await self._search(key, kind)

    async def _search(self, key: RecordKey, kind: EntityKind) -> Partial:
        name = "album" if kind is EntityKind.ALBUM else "track"
        response = await self.client.get(
            f"{SITE}/search/{quote(f'{key.artist} {key.title}')}/{name}",
        )
        document = parse_html(response.content)
        urls = []
        for anchor in document.css("a[href]"):
            url = urljoin(SITE, anchor.attributes["href"])
            match = _PATH.match(urlsplit(url).path)
            if match is not None and match.group(1) == name and url not in urls:
                urls.append(url)
        for url in urls[:_MAX_CANDIDATES]:
            try:
                partial = await self._page(url, kind)
            except NotFoundError:
                continue
            candidate = partial.candidate
            if candidate is not None and _matches(key, candidate.artist, candidate.title, kind):
                return partial
        raise NotFoundError(f"no matching Deezer {name}", url=response.url)

    async def _page(self, url: str, kind: EntityKind) -> Partial:
        response = await self.client.get(url)
        match = _PATH.match(urlsplit(response.url).path)
        if match is None or match.group(1) != kind.value:
            raise NotFoundError("Deezer page has the wrong record kind", url=response.url)
        data = _page_data(response.content, kind)
        if data is None:
            raise SourceError("Deezer page has no record data", url=response.url)
        if kind is EntityKind.ALBUM:
            return album_partial(_album(data, match.group(2), response.url))
        return track_partial(_track(data, match.group(2), response.url))


def _page_data(content: bytes, kind: EntityKind) -> dict[str, object] | None:
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


def _album(data: dict[str, object], item_id: str, url: str) -> Album:
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


def _track(data: dict[str, object], item_id: str, url: str) -> Track:
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
