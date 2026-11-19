from collections.abc import Mapping

from deadwax.core import Capability, Partial, Pass, RecordKey, SourceGroup
from deadwax.sources._search import SearchHit, SearchPageAdapter
from deadwax.sources.adapters.juno import parse as p


class JunoAdapter(SearchPageAdapter):
    """Shop review, genre, tags, label, and date of the record's Juno release."""

    name = "juno"
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
        """Search of every field; results list each release's tracks."""
        return f"{p.SITE}/search/", {"q[all][]": f"{key.artist} {key.title}"}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- results carry their own links
        """Releases and their tracks from the search page."""
        return p.search_hits(content)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read a product page."""
        return p.page_partial(content, url, key)
