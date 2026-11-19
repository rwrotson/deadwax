from collections.abc import Mapping

from deadwax.core import (
    Capability,
    Credit,
    EntityKind,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordKey,
    SourceGroup,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._search import pick_hit, search_key
from deadwax.sources.adapters.secondhandsongs import models
from deadwax.sources.adapters.secondhandsongs import parse as p

API = "https://api.secondhandsongs.com"
COVERS = 50


class SecondHandSongsAdapter(HttpAdapter):
    """Originals, covers, adaptations, and writers of a song from SecondHandSongs."""

    name = "secondhandsongs"
    pass_ = Pass.ENRICH
    group = SourceGroup.CATALOGUES
    service = None
    capabilities = frozenset({Capability.IDENTITY, Capability.CREDITS, Capability.RELATIONS})

    def headers(self) -> Mapping[str, str]:
        """JSON answers, and the API key when one is set."""
        api_key = self.config.sources.secondhandsongs.api_key
        key = {"x-api-key": api_key.get_secret_value()} if api_key is not None else {}
        return {"accept": "application/json", **key}

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Find the performance and read its originals or covers and its works.

        SecondHandSongs describes songs, so an album query contributes nothing.
        """
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        if key.kind is EntityKind.ALBUM:
            return Partial(source=self.name)

        performance = await self._get(models.Performance, await self._find(key))
        relations = (
            p.covers(performance, COVERS)
            if performance.is_original
            else p.originals(performance, await self._originals(performance), COVERS)
        )
        writers: list[Credit] = []
        for work_ref in performance.works:
            work = await self._get(models.Work, work_ref.uri)
            writers += p.writers(work)
            relations += p.adaptations(work)
        return Partial(
            source=self.name,
            candidate=p.candidate(performance),
            credits=writers,
            relations=relations,
        )

    async def _get[M: models.ApiModel](self, model: type[M], url: str) -> M:
        response = await self.client.get(url)
        return model.model_validate_json(response.content)

    async def _find(self, key: RecordKey) -> str:
        results = await self.client.get(
            f"{API}/search/performance",
            params={"title": key.title, "performer": key.artist},
        )
        hits = p.search_hits(models.SearchResults.model_validate_json(results.content))
        hit = pick_hit(key, hits)
        if hit is None:
            raise NotFoundError("no matching SecondHandSongs performance", url=results.url)
        return hit.url

    async def _originals(self, performance: models.Performance) -> dict[str, models.Performance]:
        """Original performances of the works a non-original performance performs, by URI."""
        found: dict[str, models.Performance] = {}
        for work in performance.originals:
            if work.original is not None and work.original.uri not in found:
                found[work.original.uri] = await self._get(models.Performance, work.original.uri)
        return found
