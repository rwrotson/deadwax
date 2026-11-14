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
    HttpSettings,
    LastfmSettings,
    Query,
    SoundCloudSettings,
    SourceGroup,
    SourcesConfig,
    SpotifySettings,
    YouTubeSettings,
    parse_query,
)
from deadwax.sources import lookup

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SECRET_PARAMS = frozenset({"key", "api_key", "token", "client_id"})
HOSTS = {
    "musicbrainz.org": "musicbrainz",
    "itunes.apple.com": "itunes",
    "api.deezer.com": "deezer",
    "song.link": "odesli",
    "album.link": "odesli",
    "api.discogs.com": "discogs",
    "www.discogs.com": "discogs",
    "bandcamp.com": "bandcamp",
    "ws.audioscrobbler.com": "lastfm",
    "www.wikidata.org": "wikipedia",
    "api.listenbrainz.org": "listenbrainz",
    "labs.api.listenbrainz.org": "listenbrainz",
    "critiquebrainz.org": "listenbrainz",
    "api.secondhandsongs.com": "secondhandsongs",
    "api.kexp.org": "kexp",
    "api.spotify.com": "spotify",
    "accounts.spotify.com": "spotify",
    "www.googleapis.com": "youtube",
    "api-v2.soundcloud.com": "soundcloud",
    "www.beatport.com": "beatport",
    "hardwax.com": "hardwax",
    "www.soundohm.com": "soundohm",
    "www.juno.co.uk": "juno",
}

ALL_GROUPS = tuple(SourceGroup)

# Recorded in place of a real Spotify access token.
STAND_IN_GRANT = '{"access_token": "test-token", "token_type": "Bearer", "expires_in": 3600}'

# Stands in for a credential of a source that is replayed: its requests must still be made.
REPLAY_CREDENTIAL = "replay"

# Sources recorded live by default; the others replay their existing fixtures when present.
LIVE_DEFAULT = ("bandcamp", "discogs")

SCENARIOS: dict[str, Query] = {
    "paranoid_android": parse_query("Radiohead - Paranoid Android", EntityKind.TRACK),
    "huerco_s": parse_query(
        "Huerco S. - For Those of You Who Have Never (And Also Those Who Have)",
        EntityKind.ALBUM,
    ),
    "kino": parse_query("Кино - Группа крови", EntityKind.TRACK),
    "missing_remix": parse_query(
        "Everything but the Girl - Missing (Todd Terry Remix)",
        EntityKind.TRACK,
    ),
    "spotify_url": parse_query("https://open.spotify.com/track/6LgJvl0Xdtc73RJ1mmpotq"),
    "apple_url": parse_query(
        "https://music.apple.com/us/album/paranoid-android/1097861387?i=1097861770",
    ),
    "no_match": parse_query("Zzqx Nonexistent Artist - No Such Song At All", EntityKind.TRACK),
    "bandcamp_url": parse_query(
        "https://brianleeds.bandcamp.com/album/for-those-of-you-who-have-never-and-also-those-who-have",
    ),
    "discogs_url": parse_query("https://www.discogs.com/master/21491-Radiohead-OK-Computer"),
    "siren_covers": parse_query("Tim Buckley - Song to the Siren", EntityKind.TRACK),
    "stronger_samples": parse_query("Kanye West - Stronger", EntityKind.TRACK),
    "reckoner": parse_query("Radiohead - Reckoner", EntityKind.TRACK),
    "soundcloud_url": parse_query("https://soundcloud.com/radiohead/paranoid-android"),
}


def source_of(host: str) -> str:
    """Name the source a host belongs to; Bandcamp pages and Wikipedias live on subdomains."""
    if host.endswith(".bandcamp.com"):
        return "bandcamp"
    if host.endswith(".wikipedia.org"):
        return "wikipedia"
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


def replayed_headers(recorded: dict[str, object]) -> dict[str, str]:
    """Headers of a recorded response: its content type and, for a redirect, its target."""
    headers = {"content-type": str(recorded["content_type"])}
    if "location" in recorded:
        headers["location"] = str(recorded["location"])
    return headers


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
            headers=replayed_headers(recorded),
            content=str(recorded["body"]).encode(),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Serve a replayed response, or send the request uncompressed and store the response."""
        # Requests that follow a redirect arrive with an unread body stream.
        await request.aread()

        source = source_of(request.url.host)
        key = fixture_key(request)
        replayed = self._replayed(source, key)
        if replayed is not None:
            sys.stdout.write(f"  replay {replayed.status_code} {key}\n")
            return replayed

        request.headers["accept-encoding"] = "identity"
        response = await self.inner.handle_async_request(request)
        body = await response.aread()
        entry: dict[str, object] = {
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body": body.decode("utf-8", "replace"),
        }
        if request.url.host == "accounts.spotify.com" and response.is_success:
            entry["body"] = STAND_IN_GRANT
        if "location" in response.headers:
            entry["location"] = response.headers["location"]
        self.recorded.setdefault(source, {})[key] = entry
        sys.stdout.write(f"  {response.status_code} {key}\n")
        return httpx.Response(response.status_code, headers=response.headers, content=body)

    async def aclose(self) -> None:
        """Close the network transport."""
        await self.inner.aclose()


def credential(source: str, variable: str, scenario: str, live: frozenset[str]) -> SecretStr | None:
    """A credential from the environment for a source recorded live.

    A replayed source gets a stand-in when it has fixtures, so that it makes their requests,
    and none otherwise, so that it is skipped instead of sending a stand-in to the network.
    """
    if source in live:
        value = os.environ.get(variable)
        return SecretStr(value) if value else None
    return SecretStr(REPLAY_CREDENTIAL) if load(scenario, source) is not None else None


def config(scenario: str, live: frozenset[str]) -> SourcesConfig:
    """Default settings with the credentials of the sources recorded live from the environment.

    The Discogs token and the Last.fm key are read from DEADWAX_DISCOGS__TOKEN and
    DEADWAX_LASTFM__API_KEY, and only for a source recorded live: a replayed source must make
    the requests its fixtures hold.

    Escalation is off because only plain httpx responses pass through the recording
    transport, and the timeout is long because Discogs allows 25 requests a minute without
    a token.
    """
    token = os.environ.get("DEADWAX_DISCOGS__TOKEN") if "discogs" in live else None
    lastfm_key = os.environ.get("DEADWAX_LASTFM__API_KEY") if "lastfm" in live else None
    return SourcesConfig(
        http=HttpSettings(escalation=()),
        adapter_timeout=180,
        discogs=DiscogsSettings(token=SecretStr(token) if token else None),
        lastfm=LastfmSettings(api_key=SecretStr(lastfm_key) if lastfm_key else None),
        spotify=SpotifySettings(
            client_id=credential("spotify", "DEADWAX_SPOTIFY__CLIENT_ID", scenario, live),
            client_secret=credential("spotify", "DEADWAX_SPOTIFY__CLIENT_SECRET", scenario, live),
        ),
        youtube=YouTubeSettings(
            api_key=credential("youtube", "DEADWAX_YOUTUBE__API_KEY", scenario, live),
        ),
        soundcloud=SoundCloudSettings(
            client_id=credential("soundcloud", "DEADWAX_SOUNDCLOUD__CLIENT_ID", scenario, live),
        ),
    )


async def record(name: str, query: Query, live: frozenset[str]) -> Dossier:
    """Run one lookup and write the fixtures of the sources recorded live."""
    transport = RecordingTransport(name, live)
    try:
        # Every source runs, opt-in ones too, so that each has fixtures for every scenario.
        dossier = await lookup(query, config(name, live), include=ALL_GROUPS, transport=transport)
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
