from collections.abc import Collection

import httpx

from deadwax.core import Dossier, Query, Request, SourceInfo, expand_names
from deadwax.sources._http import HttpResources
from deadwax.sources.client import Deadwax
from deadwax.sources.config import LookupConfig
from deadwax.sources.registry import build_adapters


def describe_sources(config: LookupConfig | None = None) -> list[SourceInfo]:
    """List the sources with their group, pass, capabilities, record kinds, requirements, status.

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
            kinds=sorted(adapter.lookups.kinds),
            requires=list(adapter.requires),
            status=adapter.status(),
            access=adapter.access(),
        )
        for adapter in adapters
    ]


async def lookup(
    request: Request | Query,
    config: LookupConfig | None = None,
    *,
    include: Collection[str] | None = None,
    exclude: Collection[str] = (),
    transport: httpx.AsyncBaseTransport | None = None,
) -> Dossier:
    """Collect what the sources know about the queried record, with a client for one call.

    A bare query asks for every facet. `include` and `exclude` take source and group names;
    without `include` the sources of `config.default_sources` run. `transport` replaces the
    network, for tests and recorded responses.
    """
    async with Deadwax(config, transport=transport) as client:
        return await client.lookup(request, include=include, exclude=exclude)
