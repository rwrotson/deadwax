import json

import httpx
import pytest
from pydantic import SecretStr

from deadwax.core import EntityKind, LookupContext, RelationKind, TextKind, parse_query
from deadwax.sources import GeniusSettings, SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.genius import GeniusAdapter, _lyrics

SONG = {
    "id": 42,
    "title": "Example Song",
    "url": "https://genius.com/Example-song-lyrics",
    "primary_artist": {"name": "Example Artist"},
    "description": {"plain": "A song about weather."},
    "writer_artists": [{"name": "A Writer"}],
    "producer_artists": [{"name": "A Producer"}],
    "song_relationships": [
        {
            "relationship_type": "samples",
            "songs": [{"title": "Earlier Song", "primary_artist": {"name": "Another Artist"}}],
        },
    ],
}


def response(request: httpx.Request) -> httpx.Response:
    payload: dict[str, object]
    if request.url.path == "/search":
        payload = {"response": {"hits": [{"result": SONG}]}}
    elif request.url.path == "/songs/42":
        payload = {"response": {"song": SONG}}
    elif request.url.path == "/referents":
        payload = {
            "response": {
                "referents": [
                    {
                        "annotations": [
                            {
                                "body": {"plain": "An explanation."},
                                "url": "https://genius.com/annotations/1",
                            },
                        ],
                    },
                ],
            },
        }
    else:
        return httpx.Response(
            200,
            text='<div data-lyrics-container="true">First line<br>Second line</div>',
        )
    return httpx.Response(200, content=json.dumps(payload).encode())


@pytest.mark.asyncio
async def test_song_facts_and_lyrics() -> None:
    config = SourcesConfig(genius=GeniusSettings(token=SecretStr("test-token")))
    adapter = GeniusAdapter(config, HttpResources(transport=httpx.MockTransport(response)))
    query = parse_query("Example Artist - Example Song", kind=EntityKind.TRACK)
    try:
        partial = await adapter.lookup(query, LookupContext(query=query))
    finally:
        await adapter.aclose()

    assert partial.candidate is not None
    assert {text.kind for text in partial.texts} == {
        TextKind.EDITORIAL,
        TextKind.USER,
        TextKind.LYRICS,
    }
    assert (
        next(text.body for text in partial.texts if text.kind is TextKind.LYRICS)
        == "First line\nSecond line"
    )
    assert {credit.role for credit in partial.credits} == {"writer", "producer"}
    assert partial.relations[0].kind is RelationKind.SAMPLES
    assert partial.errors == []


def test_empty_lyrics() -> None:
    assert _lyrics(b"<html></html>") == ""


@pytest.mark.asyncio
async def test_missing_song() -> None:
    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": {"hits": []}})

    config = SourcesConfig(genius=GeniusSettings(token=SecretStr("test-token")))
    adapter = GeniusAdapter(config, HttpResources(transport=httpx.MockTransport(empty)))
    query = parse_query("Example Artist - Example Song", kind=EntityKind.TRACK)
    try:
        with pytest.raises(Exception, match="no matching Genius song"):
            await adapter.lookup(query, LookupContext(query=query))
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_blocked_page_keeps_api_facts() -> None:
    def blocked(request: httpx.Request) -> httpx.Response:
        if request.url.host == "genius.com":
            return httpx.Response(403, text="Just a moment...")
        return response(request)

    config = SourcesConfig(genius=GeniusSettings(token=SecretStr("test-token")))
    adapter = GeniusAdapter(config, HttpResources(transport=httpx.MockTransport(blocked)))
    query = parse_query("Example Artist - Example Song", kind=EntityKind.TRACK)
    try:
        partial = await adapter.lookup(query, LookupContext(query=query))
    finally:
        await adapter.aclose()

    assert partial.candidate is not None
    assert any(text.kind is TextKind.EDITORIAL for text in partial.texts)
    assert all(text.kind is not TextKind.LYRICS for text in partial.texts)
    assert partial.errors
