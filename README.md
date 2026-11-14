# deadwax

Collect what open sources know about one track or album:

1. texts that describe how this exact release sounds: tags, credits, reviews, label and shop copy;
2. relations for further digging: members and their projects, label and neighbouring releases, compilations, mixes and broadcasts, covers, remixes, samples, similar recordings;
3. identity of the exact recording and version — original, remix, demo, live, remaster, or cover are never mixed, and disagreements between sources are shown, not smoothed over;
4. listening links on streaming services.

Every fact carries the source and URL where it was found. Nothing is invented: missing data leaves a field empty. The result is equally usable in a terminal and as JSON for other programs.

> **Status:** v1, with the eight sources listed below. The specification, stages, and progress log are in [`DEADWAX_PLAN.md`](https://github.com/rwrotson/deadwax/blob/main/DEADWAX_PLAN.md).

## Usage

```bash
deadwax --track "Burial - Archangel"
deadwax https://open.spotify.com/track/6LgJvl0Xdtc73RJ1mmpotq
deadwax --album "Burial - Untrue" --sources musicbrainz,itunes --format json
deadwax --album "Burial - Untrue" --sources core --exclude bandcamp
deadwax sources
deadwax runs --failed
```

A text query must state `--album` or `--track`; a URL implies its kind. `--sources` and `--exclude` take source and group names (`core`, `shops`, `press`, `catalogues`, `radio`, `streaming`, `samples`); without `--sources`, the sources of `DEADWAX_DEFAULT_SOURCES` (default `core,listenbrainz,secondhandsongs,kexp,spotify,youtube`) run. Other options: `--exclude`, `--format pretty|json|markdown`, `--no-cache`, `--timeout`, `--config`, `--verbose` (or `--debug`) for diagnostic stderr logs. Normal runs print the dossier and its error summary without logs. Exit codes: 0 found, 1 unexpected error, 2 usage or configuration error, 3 nothing matched.

Every `lookup` and `sources` call is journaled in the user log directory: one JSON Lines file of trace events per run (HTTP requests, every comparison with its scores and failed checks, search picks, each source's outcome, the merge's verdicts) and a summary line per run. `deadwax runs` lists runs (`--failed`, `--no-match`, `--source`, `--kind`, `--query`), and `deadwax runs ID` shows one run's timeline; see [the run journal](https://rwrotson.github.io/deadwax/runs/). `DEADWAX_RUNS__ENABLED=false` turns it off.

```python
import asyncio

from deadwax import EntityKind, SourcesConfig, lookup, parse_query

dossier = asyncio.run(
    lookup(parse_query("Burial - Archangel", kind=EntityKind.TRACK), SourcesConfig())
)
print(dossier.model_dump_json(indent=2))
```

## Installation

| Install | Adds |
|---------|------|
| `deadwax` | The library: Pydantic, httpx, selectolax |
| `deadwax[logs]` | `deadwax.logs`: `LogSettings`, `setup_logging()`, and the run journal (structlog) |
| `deadwax[cli]` | The `deadwax` command (Typer, Pydantic Settings, rich, platformdirs) and `logs` |
| `deadwax[stealth]` | curl_cffi browser TLS impersonation for pages behind bot protection |
| `deadwax[browser]` or `deadwax[patchright]` | Patchright Chromium HTML transport (`patchright install chromium`) |
| `deadwax[nodriver]` | Nodriver Chrome HTML transport (install Chrome separately) |

## Sources

Every source is described in detail in [the sources guide](https://rwrotson.github.io/deadwax/sources/); the output is described in [the output guide](https://rwrotson.github.io/deadwax/output/).

### Tier 1: identity and links

| Source | Status | Contributes | Caveats |
|--------|--------|-------------|---------|
| MusicBrainz | implemented | identity, ISRCs, labels, credits, tags and genres, members, covers, remixes, samples, appearances on releases and compilations, streaming links, Discogs and Wikidata IDs; resolves MusicBrainz URLs, and Spotify URLs when Spotify has no credentials | the only identity-pass source; the public server is often busy (retried) |
| iTunes Search | implemented | Apple Music links and previews, release date, genre; resolves Apple Music URLs | about 20 requests a minute |
| Deezer | implemented | Deezer links, plus ISRC, barcode, label, and genres when present in HTML; resolves Deezer URLs | HTML can be blocked or omit fields; no API fallback |
| Odesli (song.link) | implemented | links on every platform Odesli matches, with the title and ISRC or UPC; resolves streaming URLs | no public API since 2026-07-31: reads the song.link page of a streaming link from the query or an earlier source (MusicBrainz, iTunes, Deezer), else `not_found` |

### Tier 2: enrichment

| Source | Status | Contributes | Caveats |
|--------|--------|-------------|---------|
| Discogs | implemented; search needs `discogs.token` | genres and styles, credits with roles and tracks, notes, labels with catalog numbers, barcodes, other versions of the master, compilations, the label's other releases, members, groups, aliases, user reviews; resolves Discogs URLs | without a token reads only the IDs MusicBrainz gives (25 requests a minute); sends httpx's User-Agent because Discogs refuses deadwax's; review pages may be `blocked` |
| Bandcamp | implemented | tags, About and Credits texts, credits, fan comments, recommendations as similar releases, label, the label's other releases; resolves `bandcamp.com` album and track pages | scraped pages; a track found on another artist's album contributes only its identity, links and own notes |
| Last.fm | implemented, needs `lastfm.api_key` | weighted tags (artist-wide ones marked `artist`), wiki texts, similar tracks or artists | `skipped` without the key |
| Wikipedia/Wikidata | implemented | genres, producers, composers, lyricists, labels, date, the album a song is on, review scores, lead and music sections of the English and original-language articles | section headings recognised in en, ru, ja, de, fr; other languages give the lead |
| ListenBrainz | implemented | listen and listener counts, similar recordings and artists, CritiqueBrainz reviews | needs MusicBrainz IDs from the identity pass |
| SecondHandSongs | implemented | first release date, writers, covers, the original of a cover, adaptations | songs only; about 10–20 requests a minute without `secondhandsongs.api_key` |
| KEXP | implemented | the latest 25 plays as broadcasts with programs and hosts, host comments | |
| Spotify | implemented, needs `spotify.client_id` and `spotify.client_secret` | links, ISRC or barcode, ℗ and © lines; label, popularity, and previews when Spotify gives them; resolves Spotify URLs | `skipped` without credentials; development-mode apps get no label, popularity, or previews; no audio features |
| YouTube | implemented, needs `youtube.api_key` | links to uploads of the record only, official channels first | about 100 lookups a day on the free quota |
| Beatport | implemented, opt-in | tempo, key, genre and sub-genre, mix name as the version, ISRC, label and catalog number, remixers, DJ charts that list the track; resolves Beatport URLs | Cloudflare: needs the `stealth` or `browser` extra, else `blocked` |
| Hard Wax | implemented, opt-in | one-line shop text, store section as genre, label and catalog number, the release a track is on; resolves Hard Wax product pages | searched through the shop's JSON feed |
| Soundohm | implemented, opt-in | full shop text (often the label's press release), genre, label, catalog number, year; resolves Soundohm product pages | albums only: product pages list no tracks |
| Juno | implemented, opt-in | shop review, genre and Juno tags, label and catalog number, release date, the release a track is on; resolves Juno product pages | Cloudflare: needs the `stealth` or `browser` extra, else `blocked`; built on pages saved from a browser |
| Forced Exposure | implemented, opt-in | label copy, genre, release date, label, catalog number, related releases | Patchright first; albums only |
| Bleep | implemented, opt-in | editorial description, genres, release date, label, catalog number, tracklist | Patchright first |
| Phonica | implemented, opt-in | shop description, genres, release details | Patchright headless; search title and artist separately through a browser session |
| Boomkat | implemented, opt-in | editorial description and genres | Patchright with a visible window; headless meets Cloudflare |
| Norman Records | implemented, opt-in | release identity and genres from a product URL | Nodriver with a visible window; text search is unavailable |
| SoundCloud | implemented, opt-in, needs `soundcloud.client_id` | uploader descriptions, genre and tags, plays, likes and reposts, notable reposting accounts, uploads absent elsewhere (edits, bootlegs) as other versions; resolves SoundCloud URLs | no new API apps: the web client's ID changes now and then and must be replaced by hand |
| Genius | implemented, default, needs `genius.token` | song description, annotations, credits, song relations, full lyrics when available | API facts remain when the HTML page is blocked |
| AllMusic | experimental, opt-in | review, rating, critic, styles, moods, themes, credits, similar albums | Live pages currently return Cloudflare 403 from the development network; extraction awaits saved-page verification |
| Album of the Year | experimental, opt-in | critic scores, user score, genres, links to critic reviews | Live pages currently return Cloudflare 403 from the development network; extraction awaits saved-page verification |

Names written in a non-Latin script are compared as written: a store that lists "Кино" as "Kino" is reported as `no_match`.

### Planned

| Group | Sources | Caveats |
|-------|---------|---------|
| Shops | Boomkat, Norman | access blocked by Cloudflare |
| Reviews and press | Resident Advisor (GraphQL), press reviews through one adapter with per-site rules | |
| Catalogues and communities | Rate Your Music | Rate Your Music only through a browser |
| Radio and mixes | NTS, 1001Tracklists, WFMU | |
| Samples | WhoSampled | needs a separate decision on its terms of service |

Deferred: Phonica (Sucuri), Boomkat and Norman Records (Cloudflare), until access is solved.

Never used: Juno Download (shut down), Every Noise at Once, direct Metacritic scraping (Metacritic scores come from Wikipedia), Spotify audio features.

## Configuration

The library takes settings as arguments and never reads the environment. The `deadwax` command loads `deadwax.cli.settings.Settings` from flags, `DEADWAX_*` environment variables, `.env`, and a TOML file (`--config`, `DEADWAX_CONFIG_FILE`, or `config.toml` in the user configuration directory), in that order of precedence; sections are nested with `__` (for example `DEADWAX_LASTFM__API_KEY=…`) or TOML tables (`[lastfm]`). The command caches responses in the user cache directory. Requests use the proxy from the environment (`HTTPS_PROXY`, `NO_PROXY`); `DEADWAX_HTTP__PROXY` or `DEADWAX_<SOURCE>__PROXY` set `direct` or another proxy, for example `DEADWAX_DEEZER__PROXY=direct` when a site refuses the proxy's address. For HTML requests, each source has an ordered `html_transports` list in code, overridable by a TOML array or `DEADWAX_<SOURCE>__HTML_TRANSPORTS` JSON array. `DEADWAX_HTTP__BROWSER_HEADLESS=false` shows the browser globally; `DEADWAX_<SOURCE>__BROWSER_HEADLESS` sets a source's mode. `DEADWAX_HTTP__PATCHRIGHT_CHANNEL=chrome` selects installed Chrome with a temporary profile. `DEADWAX_HTTP__PATCHRIGHT_PROFILE_DIR` or `DEADWAX_HTTP__NODRIVER_PROFILE_DIR` opts into a dedicated persistent profile for one transport; never use your regular Chrome profile. `DEADWAX_HTTP__BROWSER_CHALLENGE_WAIT` controls how long browser transports wait for a challenge or required page state. On one lookup, `--headless` or `--headed` overrides all source modes, and `--html-transport browser,nodriver` sets the exact HTML transport order without changing saved settings. See `.env.example` and the generated configuration page in the documentation.

### Credentials

Sources without their credential are `skipped` (or, where noted, work with less); `deadwax sources` shows which are missing. Put the values in `.env` or the environment; never commit them.

| Setting | Source | Needed |
|---------|--------|--------|
| `DEADWAX_DISCOGS__TOKEN` | Discogs | for search; without it only IDs from MusicBrainz are read |
| `DEADWAX_LASTFM__API_KEY` | Last.fm | for every lookup |
| `DEADWAX_SECONDHANDSONGS__API_KEY` | SecondHandSongs | optional; raises the request limit |
| `DEADWAX_SPOTIFY__CLIENT_ID`, `DEADWAX_SPOTIFY__CLIENT_SECRET` | Spotify | for every lookup |
| `DEADWAX_YOUTUBE__API_KEY` | YouTube | for every lookup |
| `DEADWAX_SOUNDCLOUD__CLIENT_ID` | SoundCloud | for every lookup |
| `DEADWAX_GENIUS__TOKEN` | Genius | for every lookup |

**Discogs token.** Sign in at discogs.com, open [Settings → Developers](https://www.discogs.com/settings/developers), and press **Generate new token**. Copy the personal access token into `DEADWAX_DISCOGS__TOKEN`.

**Last.fm API key.** Sign in at last.fm and fill in [Create API account](https://www.last.fm/api/account/create) (application name and description; the callback URL may stay empty). Copy the **API key** into `DEADWAX_LASTFM__API_KEY`; the shared secret is not used.

**SecondHandSongs API key.** Optional. Request one as described on the [SecondHandSongs API page](https://secondhandsongs.com/page/API) and put it into `DEADWAX_SECONDHANDSONGS__API_KEY`.

**Spotify client ID and secret.** Sign in at the [Spotify developer dashboard](https://developer.spotify.com/dashboard) and press **Create app**: any name and description, any redirect URI (for example `http://127.0.0.1:8888/callback`), and **Web API** checked. In the app's **Settings**, copy **Client ID** and **Client secret** into `DEADWAX_SPOTIFY__CLIENT_ID` and `DEADWAX_SPOTIFY__CLIENT_SECRET`.

**YouTube Data API key.** In the [Google Cloud console](https://console.cloud.google.com/), create a project, open **APIs & Services → Library**, and enable **YouTube Data API v3**. Then **APIs & Services → Credentials → Create credentials → API key**; restricting the key to YouTube Data API v3 is advised. Put it into `DEADWAX_YOUTUBE__API_KEY`. The free quota of 10,000 units a day allows about 100 lookups (100 units a search).

**SoundCloud client ID.** SoundCloud registers no new API apps. The client ID of an app registered earlier (soundcloud.com/you/apps) works and does not change. Otherwise copy the ID of SoundCloud's web client by hand: open soundcloud.com with the browser's developer tools on the **Network** tab, filter for `api-v2`, and copy the `client_id` parameter (32 characters) of any request to `api-v2.soundcloud.com` into `DEADWAX_SOUNDCLOUD__CLIENT_ID`. Using the web client's ID is unofficial, and SoundCloud changes it now and then: when deadwax reports "is soundcloud.client_id stale?", copy it again.

**Genius token.** Sign in at [Genius API Clients](https://genius.com/api-clients), create an API client, open its details, and copy the client access token into `DEADWAX_GENIUS__TOKEN`.

## Development

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups --locked
uv run pre-commit install

uv run poe check       # format check, lint, import contracts, type check, tests with coverage
uv run poe fmt
uv run poe test-fast
uv run poe test-live   # opt-in lookups of real tracks against the live sources (tests/integration), keys from .env
uv run poe docs
uv run poe audit
uv build
uv run --group docs properdocs build --strict
```

Repository conventions for contributors and coding agents are in [`AGENTS.md`](https://github.com/rwrotson/deadwax/blob/main/AGENTS.md); layers and import rules in [the architecture guide](https://rwrotson.github.io/deadwax/architecture/). Commits follow [Conventional Commits](https://www.conventionalcommits.org/); `uv run cz bump` bumps the version, updates `CHANGELOG.md`, and tags the release.

## Project Structure

```
src/
└── deadwax/
    ├── __init__.py          # public API (__all__), NullHandler
    ├── py.typed             # PEP 561 marker
    ├── main.py              # deadwax console script; reports a missing cli extra
    ├── cli/                 # deadwax[cli]: Typer app, DEADWAX_* settings, rendering
    ├── logs/                # deadwax[logs]: LogSettings, setup_logging(), run_journal()
    ├── sources/             # adapters, HTTP stack, lookup()
    │   ├── musicbrainz/     # MusicBrainz models, parsers, adapter
    │   ├── discogs/         # Discogs models, parsers, adapter
    │   ├── bandcamp/        # Bandcamp models, page parsers, adapter
    │   ├── lastfm/          # Last.fm models, parsers, adapter
    │   ├── wikipedia/       # Wikidata and Wikipedia models, parsers, adapter
    │   ├── listenbrainz/    # ListenBrainz and CritiqueBrainz models, parsers, adapter
    │   ├── secondhandsongs/ # SecondHandSongs models, parsers, adapter
    │   ├── kexp/            # KEXP models, parsers, adapter
    │   ├── spotify/         # Spotify Web API models, parsers, adapter
    │   ├── soundcloud/      # SoundCloud models, parsers, adapter
    │   ├── beatport/        # Beatport page-state models, parsers, adapter
    │   ├── hardwax/         # Hard Wax search-feed models, page parsers, adapter
    │   ├── soundohm/        # Soundohm page parsers, adapter
    │   ├── juno/            # Juno page parsers, adapter
    │   └── _http/           # rate limits, retries, cache, escalation transports
    └── core/                # models, matching, orchestrator, errors (Pydantic only)
tests/                       # mirrors the package; network is disabled
├── fixtures/<source>/       # recorded responses, one file per source and scenario
├── integration/             # live lookups, collected only with --live (poe test-live)
scripts/record_fixtures.py   # re-records the fixtures from the live sources
```

## CI/CD

`.github/workflows/ci.yml` runs format, lint, import contracts and strict mypy; tests on Ubuntu and macOS with a 95% branch coverage gate; tests against the lowest allowed direct dependencies with all extras; a package build with a wheel smoke test, a strict docs build, pip-audit, and trivy. `.github/workflows/release.yml` builds on version tags, publishes to PyPI with Trusted Publishing when the `PUBLISH_TO_PYPI` repository variable is `true`, and deploys the docs to GitHub Pages.

## Author

Igor Lashkov — rwrotson@yandex.ru
