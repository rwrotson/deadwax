from collections.abc import Mapping

from deadwax.core import Capability, Partial, Pass, RecordKey, SourceGroup
from deadwax.sources._search import SearchHit, SearchPageAdapter
from deadwax.sources.adapters.soundohm import parse as p


class SoundohmAdapter(SearchPageAdapter):
    """Shop text, genre, label, and year of the record's Soundohm product; albums only."""

    name = "soundohm"
    group = SourceGroup.SHOPS
    pass_ = Pass.ENRICH
    capabilities = frozenset(
        {Capability.IDENTITY, Capability.TEXTS, Capability.TAGS, Capability.LINKS},
    )
    service = p.SERVICE

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Product search."""
        return f"{p.SITE}/search", {"query": f"{key.artist} {key.title}"}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- results carry their own links
        """Products of the search page; Soundohm lists no tracks."""
        return p.search_hits(content)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:  # noqa: ARG002 -- a product is always an album
        """Read a product page."""
        return p.page_partial(content, url)
