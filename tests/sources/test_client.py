import asyncio
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from deadwax import (
    CacheSettings,
    Capability,
    Deadwax,
    EntityKind,
    LookupConfig,
    Request,
    lookup,
    parse_query,
)
from deadwax.sources import client as client_module
from deadwax.sources import registry
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import HttpResources

Replay = Callable[..., httpx.MockTransport]

pytestmark = pytest.mark.asyncio

PARANOID_ANDROID = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)


async def test_lookups_share_resources_and_build_adapters_each_time(
    monkeypatch: pytest.MonkeyPatch,
    replay: Replay,
    config: LookupConfig,
) -> None:
    built: list[tuple[int, HttpResources]] = []
    build = registry.build_adapters

    def recording(config: LookupConfig, resources: HttpResources) -> list[HttpAdapter]:
        adapters = build(config, resources)
        built.append((id(adapters[0]), resources))
        return adapters

    monkeypatch.setattr(client_module, "build_adapters", recording)

    async with Deadwax(config, transport=replay("paranoid_android")) as client:
        await asyncio.gather(
            client.lookup(PARANOID_ANDROID, include=["musicbrainz"]),
            client.lookup(PARANOID_ANDROID, include=["musicbrainz"]),
        )

    [(first, shared), (second, again)] = built
    assert shared is again
    assert first != second


async def test_cache_lives_as_long_as_the_client(
    replay: Replay,
    config: LookupConfig,
    tmp_path: Path,
) -> None:
    config = config.model_copy(update={"cache": CacheSettings(path=tmp_path / "cache.sqlite")})
    first: list[str] = []
    second: list[str] = []
    seen = first

    recorded = replay("paranoid_android")

    async def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return await recorded.handle_async_request(request)

    async with Deadwax(config, transport=httpx.MockTransport(handle)) as client:
        await client.lookup(PARANOID_ANDROID, include=["musicbrainz"])
        seen = second
        await client.lookup(PARANOID_ANDROID, include=["musicbrainz"])

    assert first
    assert second == []


async def test_lookup_needs_an_open_client(config: LookupConfig) -> None:
    client = Deadwax(config)

    with pytest.raises(RuntimeError, match="not open"):
        await client.lookup(PARANOID_ANDROID)


async def test_closing_twice_is_harmless(config: LookupConfig) -> None:
    async with Deadwax(config) as client:
        pass

    await client.aclose()


async def test_request_trims_the_dossier_to_its_facets(
    replay: Replay,
    config: LookupConfig,
) -> None:
    request = Request(query=PARANOID_ANDROID, facets=frozenset({Capability.TAGS}))

    dossier = await lookup(request, config, transport=replay("paranoid_android"))

    assert dossier.found
    assert dossier.tags
    assert (dossier.links, dossier.relations, dossier.texts) == ([], [], [])
    assert dossier.identity.title is not None
    contributors = {source.source for source in dossier.identity.title.sources}
    assert "odesli" not in contributors
    assert {"musicbrainz", "lastfm"} <= contributors
