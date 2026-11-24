from collections.abc import Mapping

from deadwax.core import (
    Capability,
    Credit,
    LookupContext,
    Lookups,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordKey,
    SourceGroup,
    VersionKind,
    parse_title,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._search import SearchHit, pick_hit, search_key
from deadwax.sources.adapters.secondhandsongs import models
from deadwax.sources.adapters.secondhandsongs import parse as p

API = "https://api.secondhandsongs.com"
COVERS = 50
COVER_CANDIDATES = 3


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

    @property
    def lookups(self) -> Lookups:
        """Songs only: SecondHandSongs describes performances."""
        return Lookups(track=self.find)

    async def find(self, query: Query, context: LookupContext) -> Partial:
        """Find the performance and read its originals or covers and its works."""
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")

        cover = key.resolved_version.kind is VersionKind.COVER
        performance = await self._cover_performance(key) if cover else await self._find(key)
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
            candidate=p.candidate(performance, cover=cover),
            credits=writers,
            relations=relations,
        )

    async def _get[M: models.ApiModel](self, model: type[M], url: str) -> M:
        response = await self.client.get(url)
        return model.model_validate_json(response.content)

    async def _search(self, key: RecordKey) -> list[SearchHit]:
        results = await self.client.get(
            f"{API}/search/performance",
            params={"title": key.title, "performer": key.artist},
        )
        return p.search_hits(models.SearchResults.model_validate_json(results.content))

    async def _find(self, key: RecordKey) -> models.Performance:
        hit = pick_hit(key, await self._search(key))
        if hit is None:
            raise NotFoundError(
                "no matching SecondHandSongs performance", url=f"{API}/search/performance"
            )
        return await self._get(models.Performance, hit.url)

    async def _cover_performance(self, key: RecordKey) -> models.Performance:
        base = RecordKey(key.artist, parse_title(key.title).base, key.kind)
        hits = await self._search(base)
        allowed = dict.fromkeys(
            hit.url for hit in hits if p.cover_identity_matches(base, key, hit.key)
        )
        for url in list(allowed)[:COVER_CANDIDATES]:
            try:
                performance = await self._get(models.Performance, url)
            except NotFoundError:
                continue
            found = p.candidate(performance)
            candidate = RecordKey(found.artist, found.title, found.kind)
            if p.cover_identity_matches(base, key, candidate) and p.has_original_artist(
                performance
            ):
                return performance
        raise NotFoundError("no confirmed SecondHandSongs cover", url=f"{API}/search/performance")

    async def _originals(self, performance: models.Performance) -> dict[str, models.Performance]:
        """Original performances of the works a non-original performance performs, by URI."""
        found: dict[str, models.Performance] = {}
        for work in performance.originals:
            if work.original is not None and work.original.uri not in found:
                found[work.original.uri] = await self._get(models.Performance, work.original.uri)
        return found
