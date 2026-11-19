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
from deadwax.sources.adapters.rateyourmusic import parse


class RateYourMusicAdapter(SearchPageAdapter):
    """Read record metadata and community reviews from Rate Your Music."""

    name = parse.SOURCE
    group = SourceGroup.CATALOGUES
    pass_ = Pass.ENRICH
    service = "rateyourmusic"
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.TAGS,
            Capability.TEXTS,
            Capability.METRICS,
            Capability.RELATIONS,
        },
    )

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search releases or songs by artist and title."""
        return "https://rateyourmusic.com/search", {
            "searchterm": f"{key.artist} {key.title}",
            "searchtype": "s" if key.kind is EntityKind.TRACK else "l",
        }

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- protocol
        """Read release and song links with their displayed identities."""
        return parse.search_hits(content)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:  # noqa: ARG002 -- protocol
        """Read the visible facts of a matched record page."""
        return parse.page_partial(content, url)
