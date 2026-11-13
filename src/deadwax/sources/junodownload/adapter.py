from collections.abc import Mapping

from deadwax.core import (
    Capability,
    EntityKind,
    NotFoundError,
    Partial,
    Pass,
    RecordKey,
    SourceGroup,
)
from deadwax.sources._base import SearchHit, SearchPageAdapter
from deadwax.sources.junodownload import parse as p


class JunoDownloadAdapter(SearchPageAdapter):
    """Tempo, genre, label, and catalog number of the record's Juno Download release."""

    name = "junodownload"
    group = SourceGroup.STREAMING
    pass_ = Pass.ENRICH
    capabilities = frozenset({Capability.IDENTITY, Capability.TAGS, Capability.LINKS})
    service = p.SERVICE

    def search_request(self, key: RecordKey) -> tuple[str, Mapping[str, str]]:
        """Search of every field, ordered by relevance."""
        terms = f"{key.artist} {key.title}"
        return f"{p.SITE}/search/", {"q[all][]": terms, "solrorder": "relevancy"}

    def search_hits(self, content: bytes, url: str) -> list[SearchHit]:  # noqa: ARG002 -- the protocol's signature
        """Releases and their tracks from a search page."""
        return p.hits(content)

    def read_page(self, content: bytes, url: str, key: RecordKey | None) -> Partial:
        """Read the release, or the track of it the key names."""
        page = p.release(content, url)
        if key is None or key.kind is not EntityKind.TRACK:
            return p.album_partial(page, url)

        track = p.find_track(page, key)
        if track is None:
            raise NotFoundError("the Juno Download release does not list the track", url=url)
        return p.track_partial(page, track, url)
