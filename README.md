# deadwax

Collect what open sources know about one track or album:

1. texts that describe how this exact release sounds: tags, credits, reviews, label and shop copy;
2. relations for further digging: members and their projects, label and neighbouring releases, compilations, mixes and broadcasts, covers, remixes, samples, similar recordings;
3. identity of the exact recording and version — original, remix, demo, live, remaster, or cover are never mixed, and disagreements between sources are shown, not smoothed over;
4. listening links on streaming services.

Every fact carries the source and URL where it was found. Nothing is invented: missing data leaves a field empty. The result is equally usable in a terminal and as JSON for other programs.

> **Status:** under development. The specification, stages, and progress log are in [`DEADWAX_PLAN.md`](https://github.com/rwrotson/deadwax/blob/main/DEADWAX_PLAN.md). The library's `lookup()` and the command work with the sources listed below.

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

| Source | Status | Contributes |
|--------|--------|-------------|
| MusicBrainz | implemented | identity, ISRCs, labels, credits, tags and genres, members, covers, remixes, samples, appearances on releases and compilations, streaming links, Discogs and Wikidata IDs; resolves MusicBrainz and Spotify URLs |
| iTunes Search | implemented | Apple Music links and previews, release date, genre; resolves Apple Music URLs |
| Deezer | implemented | Deezer links and previews, ISRC, barcode, label; resolves Deezer URLs. The API may refuse some networks; this is reported as `blocked` |
| Odesli (song.link) | implemented | links on every platform Odesli matches, read from the song.link page of a streaming link (the query URL, or a Spotify, Apple Music, Deezer, Tidal or YouTube link found earlier), with the title, ISRC, or UPC of that record; resolves streaming URLs. Odesli has no public API since 2026-07-31; the page is fetched with browser headers and the escalation ladder. Without such a link from the query or MusicBrainz it reports `not_found` |
| Discogs | implemented; search needs `discogs.token` | genres and styles, credits with roles and tracks, database notes, labels with catalog numbers, barcodes, other versions of the master, compilations (with token), the label's other releases, members, groups and aliases; user reviews from the release page through the escalation ladder (a refused page is reported as `blocked` and costs only the reviews); resolves Discogs URLs. Without a token it reads records by the Discogs IDs MusicBrainz gives, at 25 requests a minute. Discogs refused deadwax's own User-Agent on 2026-11-12, so it is sent httpx's (`discogs.user_agent` overrides it) |
| Bandcamp | implemented | tags, About and Credits texts, simple credits, fan comments, recommendations as similar releases, label from the mobile API, the label's other releases; resolves album and track pages on `bandcamp.com` subdomains. A track found on another artist's album (a compilation) contributes only its identity, links and own notes |
| Last.fm | implemented, needs `lastfm.api_key` | tags with weights (track or album, and artist-wide ones marked `artist`), wiki texts, similar tracks (for a track) or similar artists (for an album) |
| Wikipedia/Wikidata | implemented | genres, producers, composers, lyricists, labels, release date, the album a song is on, review scores (Wikidata and the ratings templates of the articles), and the lead and music-related sections of the English article and the article in the record's original language; the item comes from the Wikidata ID MusicBrainz gives, else from a Wikidata search by title, type, and performer. Section headings are recognised in English, Russian, Japanese, German, and French; other languages contribute the lead |

Other sources are planned as separate adapters; the full list with tiers will be documented here. Names written in a non-Latin script are compared as written: a store that lists "Кино" as "Kino" is reported as `no_match`.

## Configuration

The library takes settings as arguments and never reads the environment. The `deadwax` command loads `deadwax.cli.settings.Settings` from flags, `DEADWAX_*` environment variables, `.env`, and a TOML file (`--config`, `DEADWAX_CONFIG_FILE`, or `config.toml` in the user configuration directory), in that order of precedence; sections are nested with `__` (for example `DEADWAX_LASTFM__API_KEY=…`) or TOML tables (`[lastfm]`). The command caches responses in the user cache directory. See `.env.example` and the generated configuration page in the documentation.

## Development

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups --locked
uv run pre-commit install

uv run poe check       # format check, lint, import contracts, type check, tests with coverage
uv run poe fmt
uv run poe test-fast
uv run poe test-live   # opt-in lookups of real tracks against the live sources (tests/integration)
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
