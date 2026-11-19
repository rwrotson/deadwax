from deadwax.core import (
    Capability,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    SourceGroup,
    Text,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import Profile
from deadwax.sources._search import search_key
from deadwax.sources.adapters.pressreviews import parse


class PressAdapter(HttpAdapter):
    """Read reviews linked by earlier sources at three supported publications."""

    name = "pressreviews"
    group = SourceGroup.PRESS
    pass_ = Pass.LINKS
    profile = Profile.BROWSER
    capabilities = frozenset({Capability.TEXTS})

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Read linked reviews whose page identity matches the requested record."""
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("no record identity for press reviews")
        links = [link.url for link in context.review_links if parse.review_site(link.url)]
        if not links:
            raise NotFoundError("no supported press review links")
        texts: list[Text] = []
        candidate = None
        for url in dict.fromkeys(links):
            response = await self.client.get(url)
            review = parse.review(response.content, response.url, key)
            if review is None:
                continue
            candidate, text = review
            texts.append(text)
        if not texts:
            raise NotFoundError("no matching accessible press reviews")
        return Partial(source=self.name, candidate=candidate, texts=texts)
