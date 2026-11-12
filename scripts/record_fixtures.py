import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from deadwax import Dossier, EntityKind, Query, SourcesConfig, parse_query
from deadwax.sources import lookup

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SECRET_PARAMS = frozenset({"key", "api_key", "token"})
HOSTS = {
    "musicbrainz.org": "musicbrainz",
    "itunes.apple.com": "itunes",
    "api.deezer.com": "deezer",
    "api.song.link": "odesli",
}
SCENARIOS: dict[str, Query] = {
    "paranoid_android": parse_query("Radiohead - Paranoid Android", EntityKind.TRACK),
    "huerco_s": parse_query(
        "Huerco S. - For Those of You Who Have Never (And Also Those Who Have)", EntityKind.ALBUM
    ),
    "kino": parse_query("Кино - Группа крови", EntityKind.TRACK),
    "missing_remix": parse_query(
        "Everything but the Girl - Missing (Todd Terry Remix)", EntityKind.TRACK
    ),
    "spotify_url": parse_query("https://open.spotify.com/track/6LgJvl0Xdtc73RJ1mmpotq"),
    "apple_url": parse_query(
        "https://music.apple.com/us/album/paranoid-android/1097861387?i=1097861770"
    ),
    "no_match": parse_query("Zzqx Nonexistent Artist - No Such Song At All", EntityKind.TRACK),
}


def fixture_url(url: httpx.URL) -> str:
    """URL without secret parameters, with parameters sorted, as fixtures store it."""
    parts = urlsplit(str(url))
    params = sorted((k, v) for k, v in parse_qsl(parts.query) if k not in SECRET_PARAMS)
    return urlunsplit(parts._replace(query=urlencode(params)))


class RecordingTransport(httpx.AsyncBaseTransport):
    """Forward requests to the network and keep the last response for each request."""

    def __init__(self) -> None:
        self.inner = httpx.AsyncHTTPTransport(http2=True)
        self.recorded: dict[str, dict[str, dict[str, object]]] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Send the request uncompressed and store the response under its source."""
        request.headers["accept-encoding"] = "identity"
        response = await self.inner.handle_async_request(request)
        body = await response.aread()
        source = HOSTS.get(request.url.host, request.url.host)
        key = f"{request.method} {fixture_url(request.url)}"
        self.recorded.setdefault(source, {})[key] = {
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body": body.decode("utf-8", "replace"),
        }
        sys.stdout.write(f"  {response.status_code} {key}\n")
        return httpx.Response(response.status_code, headers=response.headers, content=body)

    async def aclose(self) -> None:
        """Close the network transport."""
        await self.inner.aclose()


async def record(name: str, query: Query) -> Dossier:
    """Run one lookup against the live sources and write its fixtures."""
    transport = RecordingTransport()
    try:
        dossier = await lookup(query, SourcesConfig(), transport=transport)
    finally:
        await transport.aclose()
    recorded_at = datetime.now(UTC).isoformat(timespec="seconds")
    for source, interactions in transport.recorded.items():
        path = FIXTURES / source / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"recorded_at": recorded_at, "interactions": interactions}
        path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n")
    return dossier


async def main(names: list[str]) -> None:
    """Record the named scenarios, or all of them."""
    for name in names or list(SCENARIOS):
        sys.stdout.write(f"{name}\n")
        dossier = await record(name, SCENARIOS[name])
        title = dossier.identity.title.value if dossier.identity.title else None
        errors = [(error.source, error.kind.value) for error in dossier.errors]
        sys.stdout.write(f"  -> {title!r}; errors: {errors}\n")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
