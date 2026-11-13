from collections.abc import Mapping
from urllib.parse import urlsplit

from deadwax.core import Capability, EntityKind, Partial, Pass, RecordKey, SourceGroup
from deadwax.sources._base import SearchHit, SearchPageAdapter
from deadwax.sources.beatport import parse as p


class BeatportAdapter(SearchPageAdapter):
    """Tempo, key, genres, mix name, ISRC, remixers, and DJ charts of the record's Beatport page."""

    name = "beatport"
    group = SourceGroup.STREAMING
    pass_ = Pass.ENRICH
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.TAGS,
            Capability.CREDITS,
            Capability.RELATIONS,
            Capability.LINKS,
        },
    )
    service = p.SERVICE

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Track or release search."""
        section = "releases" if key.kind is EntityKind.ALBUM else "tracks"
        return f"{p.SITE}/search/{section}", {"q": f"{key.artist} {key.title}"}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:
        """Results from the search page's state."""
        props = p.page_props(content, url)
        if urlsplit(url).path.rstrip("/").endswith("/releases"):
            return p.release_hits(props)
        return p.track_hits(props)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:  # noqa: ARG002 -- the URL tells tracks from releases
        """Read a track or release page."""
        return p.page_partial(content, url)
