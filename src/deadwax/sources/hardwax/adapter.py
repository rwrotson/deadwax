from collections.abc import Mapping

from deadwax.core import Capability, Partial, Pass, RecordKey, SourceGroup
from deadwax.sources._base import SearchHit, SearchPageAdapter
from deadwax.sources._http import HttpClient, HttpResources, Profile
from deadwax.sources.config import SourcesConfig
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

    def __init__(self, config: SourcesConfig, resources: HttpResources) -> None:
        super().__init__(config, resources)
        self._feed_client: HttpClient | None = None

    @property
    def search_client(self) -> HttpClient:
        """Use plain HTTP for the JSON search feed."""
        if self._feed_client is None:
            self._feed_client = HttpClient(
                self.client_spec(Profile.API), self.config, self.resources,
            )
        return self._feed_client

    async def aclose(self) -> None:
        """Close both the page and feed clients."""
        await super().aclose()
        if self._feed_client is not None:
            await self._feed_client.aclose()
            self._feed_client = None

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search through the shop's JSON feed, which lists tracklists too."""
        return f"{p.SITE}/feeds/search.json", {"find": f"{key.artist} {key.title}"}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:
        """Releases and their tracks from the search feed."""
        return p.search_hits(content, url)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read a product page."""
        return p.page_partial(content, url, key)
