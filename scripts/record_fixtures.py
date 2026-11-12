import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import SecretStr

from deadwax import (
    DiscogsSettings,
    Dossier,
    EntityKind,
    Escalation,
    HttpSettings,
    Query,
    SourcesConfig,
    parse_query,
)
from deadwax.sources import lookup

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SECRET_PARAMS = frozenset({"key", "api_key", "token"})
HOSTS = {
    "musicbrainz.org": "musicbrainz",
    "itunes.apple.com": "itunes",
    "api.deezer.com": "deezer",
    "api.song.link": "odesli",
    "api.discogs.com": "discogs",
    "www.discogs.com": "discogs",
    "bandcamp.com": "bandcamp",
}

# Sources recorded live by default; the others replay their existing fixtures when present.
LIVE_DEFAULT = ("bandcamp", "discogs")

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
    "bandcamp_url": parse_query(
        "https://brianleeds.bandcamp.com/album/for-those-of-you-who-have-never-and-also-those-who-have"
    ),
    "discogs_url": parse_query("https://www.discogs.com/master/21491-Radiohead-OK-Computer"),
}


def source_of(host: str) -> str:
    """Name the source a host belongs to; Bandcamp pages live on subdomains."""
    if host.endswith(".bandcamp.com"):
        return "bandcamp"
    return HOSTS.get(host, host)


def fixture_key(request: httpx.Request) -> str:
    """Method, URL without secret parameters and with sorted parameters, and a body hash."""
    parts = urlsplit(str(request.url))
    params = sorted((k, v) for k, v in parse_qsl(parts.query) if k not in SECRET_PARAMS)
    key = f"{request.method} {urlunsplit(parts._replace(query=urlencode(params)))}"
    if request.content:
        key += f" #{hashlib.sha256(request.content).hexdigest()[:16]}"
    return key


def load(scenario: str, source: str) -> dict[str, dict[str, object]] | None:
    """Return the recorded interactions of one source in a scenario, if any."""
    path = FIXTURES / source / f"{scenario}.json"
    if not path.exists():
        return None
    interactions: dict[str, dict[str, object]] = json.loads(path.read_text())["interactions"]
    return interactions


class RecordingTransport(httpx.AsyncBaseTransport):
    """Replay existing fixtures of some sources; forward the rest and keep their responses."""

    def __init__(self, scenario: str, live: frozenset[str]) -> None:
        self.scenario = scenario
        self.live = live
        self.inner = httpx.AsyncHTTPTransport(http2=True)
        self.recorded: dict[str, dict[str, dict[str, object]]] = {}

    def _replayed(self, source: str, key: str) -> httpx.Response | None:
        if source in self.live:
            return None
        interactions = load(self.scenario, source)
        if interactions is None:
            return None
        recorded = interactions.get(key)
        if recorded is None:
            raise LookupError(f"{source}: no recorded response for {key}; record it live")
        return httpx.Response(
            int(str(recorded["status"])),
            headers={"content-type": str(recorded["content_type"])},
            content=str(recorded["body"]).encode(),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Serve a replayed response, or send the request uncompressed and store the response."""
        source = source_of(request.url.host)
        key = fixture_key(request)
        replayed = self._replayed(source, key)
        if replayed is not None:
            sys.stdout.write(f"  replay {replayed.status_code} {key}\n")
            return replayed
        request.headers["accept-encoding"] = "identity"
        response = await self.inner.handle_async_request(request)
        body = await response.aread()
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


def config() -> SourcesConfig:
    """Default settings with the Discogs token from DEADWAX_DISCOGS__TOKEN, if set.

    Escalation is off because only plain httpx responses pass through the recording
    transport, and the timeout is long because Discogs allows 25 requests a minute without
    a token.
    """
    token = os.environ.get("DEADWAX_DISCOGS__TOKEN")
    return SourcesConfig(
        http=HttpSettings(escalation=Escalation.NONE),
        adapter_timeout=180,
        discogs=DiscogsSettings(token=SecretStr(token) if token else None),
    )


async def record(name: str, query: Query, live: frozenset[str]) -> Dossier:
    """Run one lookup and write the fixtures of the sources recorded live."""
    transport = RecordingTransport(name, live)
    try:
        dossier = await lookup(query, config(), transport=transport)
    finally:
        await transport.aclose()
    recorded_at = datetime.now(UTC).isoformat(timespec="seconds")
    for source, interactions in transport.recorded.items():
        path = FIXTURES / source / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"recorded_at": recorded_at, "interactions": interactions}
        path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n")
    return dossier


async def main() -> None:
    """Record the named scenarios, or all of them."""
    parser = argparse.ArgumentParser(description="Record live responses as test fixtures.")
    parser.add_argument("scenarios", nargs="*", help=f"any of: {', '.join(SCENARIOS)}")
    parser.add_argument(
        "--live",
        default=",".join(LIVE_DEFAULT),
        help="comma-separated sources to record live, or 'all' (default: %(default)s)",
    )
    args = parser.parse_args()
    unknown = sorted(set(args.scenarios) - set(SCENARIOS))
    if unknown:
        parser.error(f"unknown scenarios: {', '.join(unknown)}")
    live = frozenset(HOSTS.values()) if args.live == "all" else frozenset(args.live.split(","))
    for name in args.scenarios or list(SCENARIOS):
        sys.stdout.write(f"{name}\n")
        dossier = await record(name, SCENARIOS[name], live)
        title = dossier.identity.title.value if dossier.identity.title else None
        errors = [(error.source, error.kind.value) for error in dossier.errors]
        sys.stdout.write(f"  -> {title!r}; errors: {errors}\n")


if __name__ == "__main__":
    asyncio.run(main())
