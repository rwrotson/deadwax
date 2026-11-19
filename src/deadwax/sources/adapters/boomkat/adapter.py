from collections.abc import Mapping

from deadwax.core import Capability, Partial, Pass, RecordKey, SourceGroup
from deadwax.sources._search import SearchHit, SearchPageAdapter
from deadwax.sources.adapters.boomkat import parse


class BoomkatAdapter(SearchPageAdapter):
    """Read Boomkat release descriptions and genres."""

    name = "boomkat"
    group = SourceGroup.SHOPS
    pass_ = Pass.ENRICH
    capabilities = frozenset(
        {Capability.IDENTITY, Capability.TEXTS, Capability.TAGS, Capability.LINKS},
    )
    service = "boomkat"

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search Boomkat by artist and title."""
        return "https://boomkat.com/search", {"q": f"{key.artist} {key.title}"}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- relative links
        """Read the listed releases."""
        return parse.search_hits(content)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:  # noqa: ARG002 -- release page
        """Read one release page."""
        return parse.page_partial(content, url)
