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
deadwax sources
```

A text query must state `--album` or `--track`; a URL implies its kind. Other options: `--exclude`, `--format pretty|json|markdown`, `--no-cache`, `--timeout`, `--config`, `--verbose`. Exit codes: 0 found, 1 unexpected error, 2 usage or configuration error, 3 nothing matched.

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
| `deadwax[logs]` | `deadwax.logs`: `LogSettings` and `setup_logging()` (structlog) |
| `deadwax[cli]` | The `deadwax` command (Typer, Pydantic Settings, rich, platformdirs) and `logs` |
| `deadwax[stealth]` | curl_cffi browser TLS impersonation for pages behind bot protection |
| `deadwax[browser]` | Playwright fallback for pages that need a real browser (`playwright install chromium`) |

## Sources

Every source is described in detail in [the sources guide](https://rwrotson.github.io/deadwax/sources/); the output is described in [the output guide](https://rwrotson.github.io/deadwax/output/).

### Tier 1: identity and links

| Source | Status | Contributes | Caveats |
|--------|--------|-------------|---------|
| MusicBrainz | implemented | identity, ISRCs, labels, credits, tags and genres, members, covers, remixes, samples, appearances on releases and compilations, streaming links, Discogs and Wikidata IDs; resolves MusicBrainz and Spotify URLs | the only identity-pass source; the public server is often busy (retried) |
| iTunes Search | implemented | Apple Music links and previews, release date, genre; resolves Apple Music URLs | about 20 requests a minute |
| Deezer | implemented | Deezer links and previews, ISRC, barcode, label, genres; resolves Deezer URLs | Akamai refuses some networks (`blocked`) |
| Odesli (song.link) | implemented | links on every platform Odesli matches, with the title and ISRC or UPC; resolves streaming URLs | no public API since 2026-07-31: reads the song.link page of a streaming link from the query or an earlier source (MusicBrainz, iTunes, Deezer), else `not_found` |

### Tier 2: enrichment

| Source | Status | Contributes | Caveats |
|--------|--------|-------------|---------|
| Discogs | implemented; search needs `discogs.token` | genres and styles, credits with roles and tracks, notes, labels with catalog numbers, barcodes, other versions of the master, compilations, the label's other releases, members, groups, aliases, user reviews; resolves Discogs URLs | without a token reads only the IDs MusicBrainz gives (25 requests a minute); sends httpx's User-Agent because Discogs refuses deadwax's; review pages may be `blocked` |
| Bandcamp | implemented | tags, About and Credits texts, credits, fan comments, recommendations as similar releases, label, the label's other releases; resolves `bandcamp.com` album and track pages | scraped pages; a track found on another artist's album contributes only its identity, links and own notes |
| Last.fm | implemented, needs `lastfm.api_key` | weighted tags (artist-wide ones marked `artist`), wiki texts, similar tracks or artists | `skipped` without the key |
| Wikipedia/Wikidata | implemented | genres, producers, composers, lyricists, labels, date, the album a song is on, review scores, lead and music sections of the English and original-language articles | section headings recognised in en, ru, ja, de, fr; other languages give the lead |

Names written in a non-Latin script are compared as written: a store that lists "Кино" as "Kino" is reported as `no_match`.

### Planned

| Group | Sources | Caveats |
|-------|---------|---------|
| Shops | Boomkat, Juno, Norman, Forced Exposure, Hard Wax, Phonica, Soundohm, Bleep, Rough Trade | shop copy as `shop` texts |
| Reviews and press | AllMusic, Resident Advisor (GraphQL), press reviews through one adapter with per-site rules | |
| Catalogues and communities | Apple Music, Rate Your Music, Genius, Album of the Year, ListenBrainz, SecondHandSongs | Rate Your Music only through a browser |
| Radio and mixes | NTS, Mixcloud, 1001Tracklists, KEXP, WFMU, BBC Sounds | |
| Streaming and download stores | Spotify, SoundCloud, YouTube, Beatport, Juno Download, Traxsource | Spotify for search and links only; YouTube not as a fact source |
| Samples | WhoSampled | needs a separate decision on its terms of service |

Never used: Every Noise at Once, direct Metacritic scraping (Metacritic scores come from Wikipedia), Spotify audio features.

## Configuration

The library takes settings as arguments and never reads the environment. The `deadwax` command loads `deadwax.cli.settings.Settings` from flags, `DEADWAX_*` environment variables, `.env`, and a TOML file (`--config`, `DEADWAX_CONFIG_FILE`, or `config.toml` in the user configuration directory), in that order of precedence; sections are nested with `__` (for example `DEADWAX_LASTFM__API_KEY=…`) or TOML tables (`[lastfm]`). The command caches responses in the user cache directory. Requests use the proxy from the environment (`HTTPS_PROXY`, `NO_PROXY`); `DEADWAX_HTTP__PROXY` or `DEADWAX_<SOURCE>__PROXY` set `direct` or another proxy, for example `DEADWAX_DEEZER__PROXY=direct` when a site refuses the proxy's address. See `.env.example` and the generated configuration page in the documentation.

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
    ├── logs/                # deadwax[logs]: LogSettings, setup_logging()
    ├── sources/             # adapters, HTTP stack, lookup()
    │   ├── musicbrainz/     # MusicBrainz models, parsers, adapter
    │   ├── discogs/         # Discogs models, parsers, adapter
    │   ├── bandcamp/        # Bandcamp models, page parsers, adapter
    │   ├── lastfm/          # Last.fm models, parsers, adapter
    │   ├── wikipedia/       # Wikidata and Wikipedia models, parsers, adapter
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
