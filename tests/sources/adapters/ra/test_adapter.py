import json

import httpx
import pytest

from deadwax import (
    EntityKind,
    ErrorKind,
    HttpSettings,
    LookupConfig,
    Query,
    Scope,
    TextKind,
    lookup,
)
from deadwax.core import BlockedError, LookupContext, RecordKey
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.ra import ResidentAdvisorAdapter
from deadwax.sources.adapters.ra.models import Review
from deadwax.sources.adapters.ra.parse import extract, review_id


def test_review_link_and_graphql_record() -> None:
    assert review_id("https://ra.co/reviews/4920") == "4920"
    record: dict[str, object] = {
        "id": "4920",
        "type": "ALBUM",
        "title": "Burial - Untrue",
        "content": "<p>First paragraph.</p><p>Second paragraph.</p>",
        "author": {"name": "Chris Mann"},
        "artists": [{"name": "Burial", "biography": {"blurb": "Artist biography."}}],
        "labels": [{"name": "Hyperdub", "blurb": "Label biography."}],
    }
    key = RecordKey(kind=EntityKind.ALBUM, artist="Burial", title="Untrue")

    result = extract(Review.model_validate(record), key, "https://ra.co/reviews/4920")

    assert result is not None
    candidate, texts = result
    assert candidate.artist == "Burial"
    assert [text.scope for text in texts] == [Scope.RELEASE_GROUP, Scope.ARTIST, Scope.LABEL]
    assert texts[0].kind is TextKind.REVIEW
    assert texts[0].author == "Chris Mann"
    assert "First paragraph." in texts[0].body


def test_other_version_and_other_host_are_rejected() -> None:
    assert review_id("https://elsewhere.example/reviews/4920") is None
    key = RecordKey(kind=EntityKind.ALBUM, artist="Burial", title="Untrue")
    record: dict[str, object] = {
        "type": "ALBUM",
        "title": "Burial - Untrue (Live)",
        "artists": [{"name": "Burial"}],
    }

    assert extract(Review.model_validate(record), key, "https://ra.co/reviews/4920") is None


@pytest.mark.asyncio
async def test_search_finds_review_without_an_incoming_link() -> None:
    operations: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        operation = payload["operationName"]
        operations.append(operation)
        if operation == "DEADWAX_SEARCH":
            data: dict[str, object] = {
                "search": [
                    {
                        "id": "4920",
                        "value": "Burial - Untrue",
                        "contentUrl": "/reviews/4920",
                    },
                ],
            }
        else:
            data = {
                "review": {
                    "type": "ALBUM",
                    "title": "Burial - Untrue",
                    "content": "<p>Full review.</p>",
                    "artists": [{"name": "Burial"}],
                },
            }
        return httpx.Response(200, json={"data": data})

    query = Query(kind=EntityKind.ALBUM, artist="Burial", title="Untrue")
    config = LookupConfig(http=HttpSettings(escalation=()))

    result = await lookup(
        query,
        config,
        include=("ra",),
        transport=httpx.MockTransport(respond),
    )

    assert operations == ["DEADWAX_SEARCH", "DEADWAX_REVIEW"]
    assert [text.body for text in result.texts] == ["Full review."]
    assert result.errors == []


@pytest.mark.asyncio
async def test_search_rejects_another_version() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["operationName"] == "DEADWAX_SEARCH"
        return httpx.Response(
            200,
            json={
                "data": {
                    "search": [{"value": "Burial - Untrue (Live)", "contentUrl": "/reviews/5"}],
                },
            },
        )

    query = Query(kind=EntityKind.ALBUM, artist="Burial", title="Untrue")
    config = LookupConfig(http=HttpSettings(escalation=()))

    result = await lookup(
        query,
        config,
        include=("ra",),
        transport=httpx.MockTransport(respond),
    )

    assert result.texts == []
    assert result.errors[0].kind is ErrorKind.NOT_FOUND


@pytest.mark.asyncio
async def test_blocked_graphql_search() -> None:
    query = Query(kind=EntityKind.ALBUM, artist="Burial", title="Untrue")
    config = LookupConfig(http=HttpSettings(escalation=(), retries=0))
    transport = httpx.MockTransport(
        lambda _: httpx.Response(403, text="<title>Just a moment...</title>"),
    )
    adapter = ResidentAdvisorAdapter(config, HttpResources(transport=transport))

    try:
        with pytest.raises(BlockedError):
            await adapter.lookup(query, LookupContext(query=query))
    finally:
        await adapter.aclose()
