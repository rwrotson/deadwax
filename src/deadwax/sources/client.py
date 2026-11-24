from collections.abc import Awaitable, Callable, Collection
from types import TracebackType
from typing import Self
from uuid import UUID

import httpx

from deadwax.core import (
    AdapterError,
    CatalogExpansion,
    Dossier,
    ErrorKind,
    IdKind,
    InvalidQueryError,
    LookupOptions,
    Query,
    ReleaseTrack,
    Request,
    WorkPerformance,
    run,
    run_source,
    trim,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import HttpResources, ResponseCache, open_cache
from deadwax.sources.adapters.discogs import DiscogsAdapter
from deadwax.sources.adapters.musicbrainz import MusicBrainzAdapter
from deadwax.sources.config import LookupConfig
from deadwax.sources.registry import build_adapters

_MAX_CATALOG_ITEMS = 100


def _mbid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as error:
        raise InvalidQueryError("expected a MusicBrainz UUID") from error


class Deadwax:
    """Client for many lookups, sharing the response cache, rate limits, and browsers.

    Use it as an async context manager. Lookups may run concurrently; adapters and their
    HTTP clients are built for each lookup, so per-lookup state does not carry over.
    """

    def __init__(
        self,
        config: LookupConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config or LookupConfig()
        self._transport = transport
        self._cache: ResponseCache | None = None
        self._resources: HttpResources | None = None

    async def __aenter__(self) -> Self:
        self._cache = open_cache(self._config.cache)
        self._resources = HttpResources(cache=self._cache, transport=self._transport)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the browsers and the response cache."""
        resources, self._resources = self._resources, None
        cache, self._cache = self._cache, None
        if resources is not None:
            await resources.sessions.aclose()
        if cache is not None:
            cache.close()

    def _catalog_resources(self, limit: int) -> HttpResources:
        if self._resources is None:
            raise RuntimeError("the client is not open; use 'async with Deadwax(...)'")
        if type(limit) is not int or not 1 <= limit <= _MAX_CATALOG_ITEMS:
            raise InvalidQueryError(f"catalog limit must be between 1 and {_MAX_CATALOG_ITEMS}")
        return self._resources

    async def _expand_catalog[T](
        self,
        adapter: HttpAdapter,
        result_type: type[CatalogExpansion[T]],
        call: Callable[[], Awaitable[CatalogExpansion[T]]],
    ) -> CatalogExpansion[T]:
        status = adapter.status()
        if not status.ready:
            error = AdapterError(
                source=adapter.name, kind=ErrorKind.SKIPPED, reason=status.detail or status.state
            )
            return result_type(errors=[error])
        try:
            result = await run_source(adapter.name, call, self._config.adapter_timeout)
        finally:
            await adapter.aclose()
        if isinstance(result, AdapterError):
            if result.kind is ErrorKind.BLOCKED:
                result = result.model_copy(update={"access": adapter.access()})
            return result_type(errors=[result])
        return result

    async def release_tracklist(
        self,
        kind: IdKind,
        release_id: str,
        *,
        limit: int = 50,
    ) -> CatalogExpansion[ReleaseTrack]:
        """List up to 100 tracks from a specific MusicBrainz or Discogs release edition."""
        resources = self._catalog_resources(limit)
        if kind is IdKind.MUSICBRAINZ_RELEASE:
            mbid = _mbid(release_id)
            musicbrainz = MusicBrainzAdapter(self._config, resources)
            return await self._expand_catalog(
                musicbrainz,
                CatalogExpansion[ReleaseTrack],
                lambda: musicbrainz.release_tracklist(mbid, limit),
            )
        if kind is IdKind.DISCOGS_RELEASE:
            if not release_id.isascii() or not release_id.isdecimal() or not release_id.strip("0"):
                raise InvalidQueryError("expected a positive Discogs release ID")
            discogs = DiscogsAdapter(self._config, resources)
            return await self._expand_catalog(
                discogs,
                CatalogExpansion[ReleaseTrack],
                lambda: discogs.release_tracklist(release_id, limit),
            )
        raise InvalidQueryError("expected a MusicBrainz release ID or Discogs release ID")

    async def work_performances(
        self,
        work_id: str,
        *,
        limit: int = 50,
    ) -> CatalogExpansion[WorkPerformance]:
        """List up to 100 recording performances associated with a MusicBrainz Work ID."""
        resources = self._catalog_resources(limit)
        mbid = _mbid(work_id)
        musicbrainz = MusicBrainzAdapter(self._config, resources)
        return await self._expand_catalog(
            musicbrainz,
            CatalogExpansion[WorkPerformance],
            lambda: musicbrainz.work_performances(mbid, limit),
        )

    async def lookup(
        self,
        request: Request | Query,
        *,
        include: Collection[str] | None = None,
        exclude: Collection[str] = (),
    ) -> Dossier:
        """Collect the requested facts about a record.

        A bare query asks for every facet. `include` and `exclude` take source and group
        names; without `include` the sources of `config.default_sources` may run.
        """
        if self._resources is None:
            raise RuntimeError("the client is not open; use 'async with Deadwax(...)'")
        if not isinstance(request, Request):
            request = Request(query=request)
        adapters = build_adapters(self._config, self._resources)
        options = LookupOptions(
            adapter_timeout=self._config.adapter_timeout,
            include=frozenset(include if include is not None else self._config.default_sources),
            exclude=frozenset(exclude),
            concurrency=self._config.concurrency,
            facets=request.facets,
        )

        try:
            dossier = await run(request.query, adapters, options)
        finally:
            for adapter in adapters:
                await adapter.aclose()

        by_name = {adapter.name: adapter for adapter in adapters}
        errors = [
            error.model_copy(update={"access": by_name[error.source].access()})
            if error.kind is ErrorKind.BLOCKED
            else error
            for error in dossier.errors
        ]
        return trim(dossier.model_copy(update={"errors": errors}), request)
