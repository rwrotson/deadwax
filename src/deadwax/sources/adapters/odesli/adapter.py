from urllib.parse import quote

from deadwax.core import (
    Capability,
    IdKind,
    LookupContext,
    Lookups,
    NotFoundError,
    Partial,
    Pass,
    Query,
    SourceGroup,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import Profile
from deadwax.sources.adapters.odesli import parse


class OdesliAdapter(HttpAdapter):
    """Links on every streaming platform from the song.link page of a streaming link."""

    name = parse.SOURCE
    pass_ = Pass.LINKS
    group = SourceGroup.CORE
    service = None
    capabilities = frozenset({Capability.LINKS})
    profile = Profile.BROWSER

    def resolves(self, query: Query) -> bool:
        """Streaming service URLs."""
        return any(
            kind in query.ids for kind in (IdKind.SPOTIFY, IdKind.APPLE_MUSIC, IdKind.DEEZER)
        )

    @property
    def lookups(self) -> Lookups:
        """Records with a streaming URL; the song.link page tells their kind."""
        return Lookups(track=self.find, album=self.find, unresolved=self.find)

    async def find(self, query: Query, context: LookupContext) -> Partial:
        """Open the song.link page of a streaming URL from the query or an earlier pass."""
        seed = parse.seed(query, context)
        if seed is None:
            raise NotFoundError("no streaming URL to start from")
        # Encoded, the seed keeps its own query (Apple's track `?i=`) and song.link answers
        # with one redirect to the record's page instead of normalizing the path first.
        response = await self.client.get(f"{parse.SITE}{quote(seed, safe='')}")
        return parse.partial(parse.page_data(response.content, response.url))
