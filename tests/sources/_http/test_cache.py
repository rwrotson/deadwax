import logging
from pathlib import Path

import pytest

from deadwax.core import ConfigurationError
from deadwax.sources import CacheSettings
from deadwax.sources._http import Request, Response, ResponseCache, cache_key, open_cache

REQUEST = Request("GET", "https://ws.audioscrobbler.com/2.0/", (("method", "track.getInfo"),))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_key_ignores_secret_parameters_and_their_order() -> None:
    with_key = Request("GET", REQUEST.url, (("api_key", "a"), ("method", "track.getInfo")))
    other_key = Request("GET", REQUEST.url, (("method", "track.getInfo"), ("api_key", "b")))

    assert cache_key("lastfm", with_key, {"api_key"}) == cache_key("lastfm", other_key, {"api_key"})
    assert cache_key("lastfm", with_key, set()) != cache_key("lastfm", other_key, set())


def test_key_depends_on_source_method_and_body() -> None:
    post = Request("POST", REQUEST.url, REQUEST.params, body=b"{}")
    other_body = Request("POST", REQUEST.url, REQUEST.params, body=b"[]")

    keys = {
        cache_key("lastfm", REQUEST, ()),
        cache_key("odesli", REQUEST, ()),
        cache_key("lastfm", post, ()),
        cache_key("lastfm", other_body, ()),
    }

    assert len(keys) == 4


@pytest.mark.asyncio
async def test_entries_expire_after_their_ttl(tmp_path: Path) -> None:
    clock = Clock()
    cache = ResponseCache(tmp_path / "nested" / "cache.sqlite", clock=clock)
    response = Response(
        url="https://x/1", status=200, content=b"\x00body", headers={"content-type": "text/html"}
    )

    await cache.put("k", response, ttl=60)
    await cache.put("skipped", response, ttl=0)
    fresh = await cache.get("k")
    skipped = await cache.get("skipped")
    clock.now += 61
    stale = await cache.get("k")
    cache.close()

    assert fresh == response
    assert skipped is None
    assert stale is None


@pytest.mark.asyncio
async def test_broken_cache_counts_as_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache = ResponseCache(tmp_path / "cache.sqlite")
    cache.close()

    with caplog.at_level(logging.WARNING, logger="deadwax"):
        await cache.put("k", Response(url="u", status=200, content=b""), ttl=60)
        assert await cache.get("k") is None

    assert "cache write failed" in caplog.text
    assert "cache read failed" in caplog.text


def test_unusable_path_is_a_configuration_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")

    with pytest.raises(ConfigurationError, match="cannot open the response cache"):
        ResponseCache(blocker / "cache.sqlite")


def test_open_cache_follows_settings(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite"

    opened = open_cache(CacheSettings(path=path))

    assert isinstance(opened, ResponseCache)
    opened.close()
    assert open_cache(CacheSettings()) is None
    assert open_cache(CacheSettings(path=path, enabled=False)) is None
