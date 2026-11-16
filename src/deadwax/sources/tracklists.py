import re
from collections.abc import Mapping
from urllib.parse import urlencode, urljoin, urlsplit

from deadwax.core import (
    Capability,
    Entity,
    EntityKind,
    EntityType,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    SourceError,
    SourceGroup,
    Verdict,
    compare,
)
from deadwax.sources._base import SearchHit, SearchPageAdapter, pick_hit, search_key
from deadwax.sources._html import Node, attribute, parse_html, text_of

ROOT = "https://www.1001tracklists.com"
SEARCH = f"{ROOT}/search/result.php"
MAX_SETS = 5


def _row_key(row: Node) -> RecordKey | None:
    artist = attribute(row.css_first('meta[itemprop="byArtist"]'), "content")
    full = attribute(row.css_first('meta[itemprop="name"]'), "content")
    if not artist or not full:
        return None
    title = full.removeprefix(f"{artist} - ")
    return RecordKey(artist=artist, title=title, kind=EntityKind.TRACK)


class TracklistsAdapter(SearchPageAdapter):
    """Find DJ sets containing a recording and its immediate neighbours."""

    name = "tracklists"
    group = SourceGroup.RADIO
    pass_ = Pass.ENRICH
    service = "tracklists"
    capabilities = frozenset({Capability.RELATIONS})

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Describe the site's track search form."""
        return SEARCH, {"main_search": f"{key.artist} {key.title}", "search_selection": "2"}

    async def search(self, key: RecordKey) -> str | None:
        """Submit the site's public track search form and select a matching version."""
        url, data = self.search_request(key)
        response = await self.search_client.request(
            "POST",
            url,
            headers={"content-type": "application/x-www-form-urlencoded"},
            body=urlencode(data).encode(),
        )
        hit = pick_hit(key, self.search_hits(response.content, response.url))
        return urljoin(ROOT, hit.url) if hit is not None else None

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- links are relative to ROOT
        """Read the record labels and links shown in search results."""
        hits = []
        for link in parse_html(content).css('a[href*="/track/"]'):
            label = text_of(link)
            href = attribute(link, "href")
            if not label or not href or " - " not in label:
                continue
            artist, title = label.split(" - ", 1)
            hits.append(
                SearchHit(
                    url=href,
                    key=RecordKey(artist=artist, title=title, kind=EntityKind.TRACK),
                ),
            )
        return hits

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Verify the track page before any set contributes relations."""
        page = parse_html(content)
        heading = page.css_first("h1#pageTitle")
        artist = text_of(heading.css_first("a[href*='/artist/']")) if heading else None
        if heading is None or not artist:
            raise SourceError("1001Tracklists page names no track", url=url)
        name = heading.text(deep=False, strip=True).removeprefix("-").strip()
        if (
            key is not None
            and compare(key, RecordKey(artist=artist, title=name, kind=EntityKind.TRACK)).verdict
            is not Verdict.MATCH
        ):
            raise NotFoundError("1001Tracklists page is another version", url=url)
        return Partial(
            source=self.name,
            candidate=RecordCandidate(kind=EntityKind.TRACK, artist=artist, title=name, url=url),
        )

    async def _set(self, url: str, key: RecordKey) -> list[Relation]:
        response = await self.client.get(url)
        page = parse_html(response.content)
        rows = page.css('[itemprop="tracks"]')
        positions = [
            i
            for i, row in enumerate(rows)
            if (found := _row_key(row)) is not None and compare(key, found).verdict is Verdict.MATCH
        ]
        if not positions:
            return []
        heading = (
            text_of(page.css_first("h1#pageTitle")) or text_of(page.css_first("h1")) or "DJ set"
        )
        date_match = re.search(r"-(\d{4}-\d{2}-\d{2})\.html$", urlsplit(url).path)
        date = date_match[1] if date_match else None
        set_name = heading.removesuffix(f" {date}") if date else heading
        dj = re.split(r" - | @ ", set_name, maxsplit=1)[0]
        provenance = [Provenance(source=self.name, url=url)]
        relations = [
            Relation(
                kind=RelationKind.MIX,
                target=Entity(type=EntityType.MIX, name=set_name, artist=dj, date=date, url=url),
                scope=Scope.RECORDING,
                sources=provenance,
            ),
        ]
        for position in positions:
            for neighbour in (position - 1, position + 1):
                if not 0 <= neighbour < len(rows):
                    continue
                found = _row_key(rows[neighbour])
                if found is None:
                    continue
                relations.append(
                    Relation(
                        kind=RelationKind.CO_PLAYED,
                        target=Entity(
                            type=EntityType.RECORDING,
                            name=found.title,
                            artist=found.artist,
                        ),
                        note="before" if neighbour < position else "after",
                        scope=Scope.RECORDING,
                        sources=provenance,
                    ),
                )
        return relations

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Find a track page, then verify the sets that list that exact track."""
        key = search_key(query, context)
        if query.kind is EntityKind.ALBUM or (key is None and not self.resolves(query)):
            raise NotFoundError("1001Tracklists needs an artist and track title")
        url = await self._page_url(query, context, key)
        response = await self.client.get(url)
        partial = self.read_page(response.content, response.url, key)
        sets = []
        for link in parse_html(response.content).css('a[href*="/tracklist/"]'):
            href = attribute(link, "href")
            if href and "#tr_" in href:
                set_url = urljoin(ROOT, href).split("#", 1)[0]
                if set_url not in sets:
                    sets.append(set_url)
        candidate = partial.candidate
        if candidate is None:
            raise SourceError("1001Tracklists page names no track", url=response.url)
        confirmed = RecordKey(
            artist=candidate.artist,
            title=candidate.title,
            kind=EntityKind.TRACK,
        )
        relations = [r for set_url in sets[:MAX_SETS] for r in await self._set(set_url, confirmed)]
        if not relations:
            raise NotFoundError("no verified 1001Tracklists set with this track", url=response.url)
        return partial.model_copy(update={"relations": relations})
