import asyncio
import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Collection
from pathlib import Path

from deadwax.core import ConfigurationError
from deadwax.sources._http.messages import Request, Response
from deadwax.sources.config import CacheSettings

logger = logging.getLogger(__name__)

_SELECT = "select url, status, headers, content from responses where key = ? and expires >= ?"
_SCHEMA = """
create table if not exists responses (
    key text primary key,
    url text not null,
    status integer not null,
    headers text not null,
    content blob not null,
    expires real not null
)
"""


def cache_key(source: str, request: Request, secret_params: Collection[str]) -> str:
    """Return the cache key of a request, leaving out the values of secret parameters."""
    params = sorted((name, value) for name, value in request.params if name not in secret_params)
    body = hashlib.sha256(request.body).hexdigest() if request.body is not None else None
    material = json.dumps([source, request.method, request.url, params, body])
    return hashlib.sha256(material.encode()).hexdigest()


class ResponseCache:
    """SQLite store of responses with a lifetime per entry."""

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(path, check_same_thread=False)
            with self._connection:
                self._connection.execute(_SCHEMA)
                self._connection.execute("delete from responses where expires < ?", (clock(),))
        except (OSError, sqlite3.Error) as error:
            message = f"cannot open the response cache at {path}: {error}"
            raise ConfigurationError(message) from error

    def _get(self, key: str) -> Response | None:
        with self._lock:
            row = self._connection.execute(_SELECT, (key, self._clock())).fetchone()
        if row is None:
            return None
        url, status, headers, content = row
        return Response(url=url, status=status, content=content, headers=json.loads(headers))

    def _put(self, key: str, response: Response, ttl: float) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "insert or replace into responses values (?, ?, ?, ?, ?, ?)",
                (
                    key,
                    response.url,
                    response.status,
                    json.dumps(dict(response.headers)),
                    response.content,
                    self._clock() + ttl,
                ),
            )

    async def get(self, key: str) -> Response | None:
        """Return a fresh cached response, or None; a broken cache counts as empty."""
        try:
            return await asyncio.to_thread(self._get, key)
        except sqlite3.Error:
            logger.warning("response cache read failed", exc_info=True)
            return None

    async def put(self, key: str, response: Response, ttl: float) -> None:
        """Store a response for `ttl` seconds; a broken cache is skipped."""
        if ttl <= 0:
            return
        try:
            await asyncio.to_thread(self._put, key, response, ttl)
        except sqlite3.Error:
            logger.warning("response cache write failed", exc_info=True)

    def close(self) -> None:
        """Close the database."""
        self._connection.close()


def open_cache(
    settings: CacheSettings, *, clock: Callable[[], float] = time.time
) -> ResponseCache | None:
    """Open the cache the settings describe, or return None when caching is off."""
    if not settings.enabled or settings.path is None:
        return None
    return ResponseCache(settings.path, clock=clock)
