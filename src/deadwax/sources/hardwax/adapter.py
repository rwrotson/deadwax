from collections.abc import Mapping

from deadwax.core import Capability, Partial, Pass, RecordKey, SourceGroup
from deadwax.sources._base import SearchHit, SearchPageAdapter
from deadwax.sources.hardwax import parse as p


class HardWaxAdapter(SearchPageAdapter):
    """Shop text, store sections, and label of the record's Hard Wax release."""

    name = "hardwax"
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
        """Search through the shop's JSON feed, which lists tracklists too."""
        return f"{p.SITE}/feeds/search.json", {"find": f"{key.artist} {key.title}"}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:
        """Releases and their tracks from the search feed."""
        return p.search_hits(content, url)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read a product page."""
        return p.page_partial(content, url, key)
