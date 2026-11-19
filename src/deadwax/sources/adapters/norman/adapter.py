from deadwax.core import (
    Capability,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    SourceGroup,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import Profile
from deadwax.sources.adapters.norman import parse
from deadwax.sources.services import service_for_url


class NormanAdapter(HttpAdapter):
    """Read Norman Records products reached by a direct or known URL."""

    name = "norman"
    group = SourceGroup.SHOPS
    pass_ = Pass.ENRICH
    profile = Profile.BROWSER
    capabilities = frozenset(
        {Capability.IDENTITY, Capability.TAGS, Capability.LINKS},
    )
    required_marker = b"<h1"

    def resolves(self, query: Query) -> bool:
        """Resolve Norman Records product URLs."""
        return query.url is not None and service_for_url(query.url) == self.name

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Read a named Norman Records product without searching the site."""
        url = query.url if self.resolves(query) else next(iter(context.urls(self.name)), None)
        if url is None:
            raise NotFoundError("Norman Records needs a product URL")
        response = await self.client.get(url)
        return parse.page_partial(response.content, response.url)
