from collections.abc import Mapping

from deadwax.core import Capability, Partial, Pass, RecordKey, SourceGroup
from deadwax.sources._base import SearchHit, SearchPageAdapter
from deadwax.sources.forcedexposure import parse


class ForcedExposureAdapter(SearchPageAdapter):
    """Label copy and release details from Forced Exposure."""

    name = "forcedexposure"
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
    service = "forcedexposure"

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search Forced Exposure release titles."""
        return "https://www.forcedexposure.com/SearchResult.html", {
            "Type": "title",
            "search": key.title,
        }

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- results carry links
        """Read releases listed by Forced Exposure."""
        return parse.search_hits(content)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:  # noqa: ARG002 -- product pages are releases
        """Read a Forced Exposure product."""
        return parse.page_partial(content, url)
