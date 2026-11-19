from collections.abc import Mapping
from urllib.parse import urlencode

from deadwax.core import Capability, Partial, Pass, RecordKey, SourceGroup
from deadwax.sources._search import SearchHit, SearchPageAdapter, pick_hit
from deadwax.sources.adapters.phonica import parse as p

# Headers the site's own search sends; its API answers JSON as text/html.
SEARCH_HEADERS = {
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "x-requested-with": "XMLHttpRequest",
}


class PhonicaAdapter(SearchPageAdapter):
    """Shop text, genres, label, and also-bought releases of the record's Phonica product."""

    name = "phonica"
    group = SourceGroup.SHOPS
    pass_ = Pass.ENRICH
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.TEXTS,
            Capability.TAGS,
            Capability.RELATIONS,
            Capability.LINKS,
        },
    )
    service = p.SERVICE

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search API URL and form for the words of the record's title."""
        term = p.search_term(key.title)
        return p.search_url(term), p.search_form(term)

    async def search(self, key: RecordKey) -> str | None:
        """Search by title, then by artist: the site finds a phrase only within one field."""
        requests = [self.search_request(key)]
        if p.search_term(key.title).casefold() != key.artist.casefold():
            requests.append((p.search_url(key.artist), p.search_form(key.artist)))
        for url, form in requests:
            response = await self.client.request(
                "POST",
                url,
                headers=SEARCH_HEADERS,
                body=urlencode(form).encode(),
            )
            hit = pick_hit(key, self.search_hits(response.content, response.url))
            if hit is not None:
                return hit.url
        return None

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:
        """Releases and their tracks from a search API answer."""
        return p.search_hits(content, url)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read a product page."""
        return p.page_partial(content, url, key)
