from collections.abc import Mapping
from urllib.parse import quote

from deadwax.core import Capability, Partial, Pass, RecordKey, SourceGroup
from deadwax.sources._base import SearchHit, SearchPageAdapter
from deadwax.sources.phonica import parse as p


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
        """Search whose words are a path segment."""
        return f"{p.SITE}/search/{quote(f'{key.artist} {key.title}', safe='')}", {}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- results carry absolute links
        """Releases from the search page."""
        return p.search_hits(content)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read a product page."""
        return p.page_partial(content, url, key)
