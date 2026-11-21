from urllib.parse import quote, urljoin, urlsplit

from deadwax.core import (
    Capability,
    EntityKind,
    IdKind,
    LookupContext,
    Lookups,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordCandidate,
    RecordKey,
    SourceError,
    SourceGroup,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._html import parse_html
from deadwax.sources._http import Profile
from deadwax.sources._search import search_key
from deadwax.sources.adapters.deezer import parse


class DeezerAdapter(HttpAdapter):
    """Deezer identity and listening links from public record pages."""

    name = parse.SOURCE
    pass_ = Pass.ENRICH
    group = SourceGroup.CORE
    service = "deezer"
    capabilities = frozenset(
        {Capability.IDENTITY, Capability.LINKS, Capability.PREVIEWS, Capability.TAGS},
    )
    profile = Profile.BROWSER

    def resolves(self, query: Query) -> bool:
        """Deezer URLs."""
        return IdKind.DEEZER in query.ids

    @property
    def lookups(self) -> Lookups:
        """Tracks and albums; the page of a query URL tells which."""
        return Lookups(track=self.find, album=self.find, unresolved=self.find)

    async def find(self, query: Query, context: LookupContext) -> Partial:
        """Read a Deezer URL or search public HTML for the requested record."""
        key = search_key(query, context)
        kind = (key.kind if key is not None else None) or query.kind or EntityKind.TRACK
        if query.url is not None and self.resolves(query):
            return await self._page(query.url, kind)
        known = next(
            (
                url
                for url in context.urls("deezer")
                if (match := parse.PATH.match(urlsplit(url).path)) is not None
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
            f"{parse.SITE}/search/{quote(f'{key.artist} {key.title}')}/{name}",
        )
        document = parse_html(response.content)
        urls = []
        for anchor in document.css("a[href]"):
            url = urljoin(parse.SITE, anchor.attributes["href"])
            match = parse.PATH.match(urlsplit(url).path)
            if match is not None and match.group(1) == name and url not in urls:
                urls.append(url)
        for url in urls[: parse.MAX_CANDIDATES]:
            try:
                partial = await self._page(url, kind)
            except NotFoundError:
                continue
            candidate = partial.candidate
            if isinstance(candidate, RecordCandidate) and parse.matches(
                key,
                candidate.artist,
                candidate.title,
                kind,
            ):
                return partial
        raise NotFoundError(f"no matching Deezer {name}", url=response.url)

    async def _page(self, url: str, kind: EntityKind) -> Partial:
        response = await self.client.get(url)
        match = parse.PATH.match(urlsplit(response.url).path)
        if match is None or match.group(1) != kind.value:
            raise NotFoundError("Deezer page has the wrong record kind", url=response.url)
        data = parse.page_data(response.content, kind)
        if data is None:
            raise SourceError("Deezer page has no record data", url=response.url)
        if kind is EntityKind.ALBUM:
            return parse.album_partial(parse.album_from_state(data, match.group(2), response.url))
        return parse.track_partial(parse.track_from_state(data, match.group(2), response.url))
