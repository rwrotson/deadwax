import dataclasses
from collections.abc import Mapping

from deadwax.core import (
    Capability,
    EntityKind,
    Partial,
    Pass,
    RecordKey,
    SourceGroup,
)
from deadwax.sources._search import SearchHit, SearchPageAdapter
from deadwax.sources.adapters.albumoftheyear import parse


class AlbumOfTheYearAdapter(SearchPageAdapter):
    """Critic scores, user score, genres, and review links from Album of the Year."""

    name = parse.SOURCE
    group = SourceGroup.CATALOGUES
    pass_ = Pass.ENRICH
    service = "albumoftheyear"
    capabilities = frozenset(
        {Capability.IDENTITY, Capability.TEXTS, Capability.TAGS, Capability.METRICS},
    )

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search Album of the Year for an album."""
        return "https://www.albumoftheyear.org/search/", {
            "q": f"{key.artist} {key.title}",
        }

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- protocol
        """Read album results."""
        return parse.search_hits(content)

    async def search(self, key: RecordKey) -> str | None:
        """Search releases; for a track, a release named after it, such as its single, counts."""
        if key.kind is not EntityKind.TRACK:
            return await super().search(key)
        return await super().search(dataclasses.replace(key, kind=EntityKind.ALBUM))

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read the release and its scores; for a track, only a release that lists it."""
        return parse.page_partial(content, url, key)
