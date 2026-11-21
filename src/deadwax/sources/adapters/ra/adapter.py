import json

from deadwax.core import (
    Capability,
    LookupContext,
    Lookups,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordKey,
    SourceError,
    SourceGroup,
    Text,
    Verdict,
    compare,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import Profile
from deadwax.sources._search import search_key
from deadwax.sources.adapters.ra import models, parse


class ResidentAdvisorAdapter(HttpAdapter):
    """Read linked RA reviews and associated artist and label biographies."""

    name = "ra"
    group = SourceGroup.PRESS
    pass_ = Pass.LINKS
    service = None
    profile = Profile.BROWSER
    capabilities = frozenset({Capability.TEXTS})

    async def _graphql(
        self,
        operation: str,
        variables: dict[str, str],
        query: str,
    ) -> models.Data:
        payload = json.dumps(
            {
                "operationName": operation,
                "variables": variables,
                "query": query,
            },
        ).encode()
        response = await self.client.request(
            "POST",
            "https://ra.co/graphql",
            headers={"content-type": "application/json"},
            body=payload,
        )
        try:
            root = models.Response.model_validate_json(response.content)
        except ValueError as error:
            raise SourceError(
                "invalid Resident Advisor GraphQL response",
                url=response.url,
            ) from error
        if root.errors:
            raise SourceError("Resident Advisor GraphQL returned errors", url=response.url)
        return root.data

    async def _search_url(self, key: RecordKey) -> str | None:
        data = await self._graphql(
            "DEADWAX_SEARCH",
            {"term": f"{key.artist} {key.title}"},
            parse.SEARCH_QUERY,
        )
        for hit in data.search:
            name = hit.value
            path = hit.content_url
            if not name or not path or parse.review_id(f"https://ra.co{path}") is None:
                continue
            artist, separator, title = name.partition(" - ")
            found_key = RecordKey(artist=artist, title=title, kind=key.kind)
            if separator and compare(key, found_key).verdict is Verdict.MATCH:
                return f"https://ra.co{path}"
        return None

    @property
    def lookups(self) -> Lookups:
        """Reviews of tracks and albums."""
        return Lookups(track=self.find, album=self.find)

    async def find(self, query: Query, context: LookupContext) -> Partial:
        """Query RA for a linked review and keep facts matching the record."""
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("no record identity for Resident Advisor")
        links = [link.url for link in context.review_links if parse.review_id(link.url)]
        if not links:
            found = await self._search_url(key)
            if found is None:
                raise NotFoundError("no matching Resident Advisor review")
            links = [found]
        texts: list[Text] = []
        candidate = None
        for url in dict.fromkeys(links):
            review_id = parse.review_id(url)
            if review_id is None:
                continue
            record = (await self._graphql("DEADWAX_REVIEW", {"id": review_id}, parse.QUERY)).review
            extracted = parse.extract(record, key, url)
            if extracted is None:
                continue
            candidate, found_texts = extracted
            texts.extend(found_texts)
        if not texts:
            raise NotFoundError("no matching Resident Advisor review")
        return Partial(source=self.name, candidate=candidate, texts=texts)
