from collections.abc import Collection
from types import TracebackType
from typing import Self

import httpx

from deadwax.core import (
    Dossier,
    ErrorKind,
    LookupOptions,
    Query,
    Request,
    run,
    trim,
)
from deadwax.sources._http import HttpResources, ResponseCache, open_cache
from deadwax.sources.config import LookupConfig
from deadwax.sources.registry import build_adapters


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
