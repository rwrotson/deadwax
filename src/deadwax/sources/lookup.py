from collections.abc import Collection

import httpx

from deadwax.core import (
    Dossier,
    ErrorKind,
    LookupOptions,
    Query,
    SourceInfo,
    expand_names,
    run,
)
from deadwax.sources._http import HttpResources, open_cache
from deadwax.sources.config import LookupConfig
from deadwax.sources.registry import build_adapters


def describe_sources(config: LookupConfig | None = None) -> list[SourceInfo]:
    """List the sources with their group, pass, capabilities, requirements, and status.

    Raises `ConfigurationError` when the default source set names an unknown source or group.
    """
    config = config or LookupConfig()
    adapters = build_adapters(config, HttpResources())
    defaults = expand_names(config.default_sources, adapters)
    return [
        SourceInfo(
            source=adapter.name,
            group=adapter.group,
            default=adapter.name in defaults,
            pass_=adapter.pass_,
            capabilities=sorted(adapter.capabilities),
            requires=list(adapter.requires),
            status=adapter.status(),
            access=adapter.access(),
        )
        for adapter in adapters
    ]


async def lookup(
    query: Query,
    config: LookupConfig | None = None,
    *,
    include: Collection[str] | None = None,
    exclude: Collection[str] = (),
    transport: httpx.AsyncBaseTransport | None = None,
) -> Dossier:
    """Collect what the sources know about the queried record.

    `include` and `exclude` take source and group names; without `include` the sources of
    `config.default_sources` run. `transport` replaces the network, for tests and recorded
    responses.
    """
    config = config or LookupConfig()
    cache = open_cache(config.cache)
    resources = HttpResources(cache=cache, transport=transport)
    adapters = build_adapters(config, resources)
    options = LookupOptions(
        adapter_timeout=config.adapter_timeout,
        include=frozenset(include if include is not None else config.default_sources),
        exclude=frozenset(exclude),
        concurrency=config.concurrency,
    )

    try:
        dossier = await run(query, adapters, options)
        by_name = {adapter.name: adapter for adapter in adapters}
        errors = [
            error.model_copy(update={"access": by_name[error.source].access()})
            if error.kind is ErrorKind.BLOCKED
            else error
            for error in dossier.errors
        ]
        return dossier.model_copy(update={"errors": errors})
    finally:
        for adapter in adapters:
            await adapter.aclose()
        await resources.sessions.aclose()
        if cache is not None:
            cache.close()
