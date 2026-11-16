from pathlib import Path

import httpx
import pytest

from deadwax import EntityKind, ErrorKind, Query, RelationKind
from deadwax.sources.config import Escalation, SourcesConfig, SourceSettings
from deadwax.sources.lookup import lookup

FIXTURES = Path(__file__).parents[1] / "fixtures" / "whosampled"


@pytest.mark.asyncio
async def test_real_record_page_extracts_connections_and_sample_offsets() -> None:
    page = (FIXTURES / "whosampled.html").read_bytes()
    sample = (FIXTURES / "sample.html").read_bytes()
    config = SourcesConfig(whosampled=SourceSettings(html_transports=(Escalation.HTTPX,)))

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sample if "/sample/" in request.url.path else page)

    dossier = await lookup(
        Query(kind=EntityKind.TRACK, artist="Daft Punk", title="One More Time"),
        config,
        include=["whosampled"],
        transport=httpx.MockTransport(respond),
    )
    assert not dossier.errors
    kinds = {item.kind for item in dossier.relations}
    assert {
        RelationKind.SAMPLES,
        RelationKind.SAMPLED_BY,
        RelationKind.COVERED_BY,
        RelationKind.REMIXED_BY,
    } <= kinds
    sample_relation = next(item for item in dossier.relations if item.kind is RelationKind.SAMPLES)
    assert sample_relation.element == "Multiple Elements"
    assert sample_relation.recording_offset == 8
    assert sample_relation.target_offset == 22
    assert sample_relation.sources[0].url is not None
    assert sample_relation.sources[0].url.startswith("https://www.whosampled.com/sample/")


@pytest.mark.asyncio
async def test_missing_record_is_reported() -> None:
    config = SourcesConfig(whosampled=SourceSettings(html_transports=(Escalation.HTTPX,)))
    dossier = await lookup(
        Query(kind=EntityKind.TRACK, artist="Daft Punk", title="One More Time"),
        config,
        include=["whosampled"],
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
    )
    assert dossier.errors[0].kind is ErrorKind.NOT_FOUND


@pytest.mark.asyncio
async def test_blocked_page_is_reported() -> None:
    config = SourcesConfig(whosampled=SourceSettings(html_transports=(Escalation.HTTPX,)))
    dossier = await lookup(
        Query(kind=EntityKind.TRACK, artist="Daft Punk", title="One More Time"),
        config,
        include=["whosampled"],
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                403,
                headers={"cf-mitigated": "challenge"},
                text="Just a moment... Cloudflare",
            ),
        ),
    )
    assert dossier.errors[0].kind is ErrorKind.BLOCKED


@pytest.mark.asyncio
async def test_different_version_adds_no_facts() -> None:
    page = (FIXTURES / "whosampled.html").read_bytes()
    config = SourcesConfig(whosampled=SourceSettings(html_transports=(Escalation.HTTPX,)))
    dossier = await lookup(
        Query(kind=EntityKind.TRACK, artist="Daft Punk", title="One More Time (Extended Mix)"),
        config,
        include=["whosampled"],
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=page)),
    )
    assert not dossier.relations
    assert dossier.errors[0].kind is ErrorKind.NOT_FOUND


@pytest.mark.asyncio
async def test_direct_record_url_needs_no_search() -> None:
    page = (FIXTURES / "whosampled.html").read_bytes()
    sample = (FIXTURES / "sample.html").read_bytes()
    config = SourcesConfig(whosampled=SourceSettings(html_transports=(Escalation.HTTPX,)))
    dossier = await lookup(
        Query(url="https://www.whosampled.com/Daft-Punk/One-More-Time/"),
        config,
        include=["whosampled"],
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=sample if "/sample/" in request.url.path else page,
            ),
        ),
    )
    assert any(item.kind is RelationKind.SAMPLES for item in dossier.relations)
