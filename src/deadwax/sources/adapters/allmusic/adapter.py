from collections.abc import Mapping
from urllib.parse import quote

from deadwax.core import (
    Capability,
    EntityKind,
    Partial,
    Pass,
    RecordKey,
    SourceGroup,
)
from deadwax.sources._search import SearchHit, SearchPageAdapter
from deadwax.sources.adapters.allmusic import parse


class AllMusicAdapter(SearchPageAdapter):
    """Reviews, credits, styles, moods, themes, and similar albums from AllMusic."""

    name = parse.SOURCE
    group = SourceGroup.PRESS
    pass_ = Pass.ENRICH
    service = "allmusic"
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.TEXTS,
            Capability.TAGS,
            Capability.CREDITS,
            Capability.RELATIONS,
        },
    )

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search AllMusic for an album or song."""
        kind = "albums" if key.kind is EntityKind.ALBUM else "songs"
        return f"https://www.allmusic.com/search/{kind}/{quote(key.title)}", {}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:
        """Read matching records in search results."""
        return parse.search_hits(content, url)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read the record's AllMusic page."""
        return parse.page_partial(content, url, key)
