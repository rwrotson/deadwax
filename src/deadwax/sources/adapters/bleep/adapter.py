from collections.abc import Mapping

from deadwax.core import Capability, Partial, Pass, RecordKey, SourceGroup
from deadwax.sources._search import SearchHit, SearchPageAdapter
from deadwax.sources.adapters.bleep import parse


class BleepAdapter(SearchPageAdapter):
    """Descriptions and release details from Bleep."""

    name = "bleep"
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
    service = "bleep"

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search release titles on Bleep."""
        return "https://bleep.com/search/query", {"q": key.title}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- results carry links
        """Read releases listed by Bleep."""
        return parse.search_hits(content)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read a Bleep release."""
        return parse.page_partial(content, url, key)
