# deadwax

Collect what open sources know about one track or album:

1. texts that describe how this exact release sounds: tags, credits, reviews, label and shop copy;
2. relations for further digging: members and their projects, label and neighbouring releases, compilations, mixes and broadcasts, covers, remixes, samples, similar recordings;
3. identity of the exact recording and version — original, remix, demo, live, remaster, or cover are never mixed, and disagreements between sources are shown, not smoothed over;
4. listening links on streaming services.

Every fact carries the source and URL where it was found. Nothing is invented: missing data leaves a field empty. The result is equally usable in a terminal and as JSON for other programs.

> **Status:** under development. The specification, stages, and progress log are in [`DEADWAX_PLAN.md`](https://github.com/rwrotson/deadwax/blob/main/DEADWAX_PLAN.md). The command below describes the planned interface.

## Usage (planned)

```bash
deadwax --track "Burial - Archangel"
deadwax https://burial.bandcamp.com/album/untrue
deadwax --album "Burial - Untrue" --sources musicbrainz,bandcamp --format json
deadwax sources
```

A text query must state `--album` or `--track`; a URL implies its kind.

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

The first version implements MusicBrainz, Odesli, Discogs, Bandcamp, Last.fm, and Wikipedia/Wikidata. Other sources are planned as separate adapters; the full list with tiers will be documented here.

## Configuration

The library takes settings as arguments and never reads the environment. The `deadwax` command loads `deadwax.cli.settings.Settings` from `DEADWAX_*` environment variables and `.env`; sections are nested with `__` (for example `DEADWAX_LOG__LEVEL=DEBUG`). See `.env.example` and the generated configuration page in the documentation.

## Development

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups --locked
uv run pre-commit install

uv run poe check       # format check, lint, import contracts, type check, tests with coverage
uv run poe fmt
uv run poe test-fast
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
    │   └── _http/           # rate limits, retries, cache, escalation transports
    └── core/                # models, matching, orchestrator, errors (Pydantic only)
tests/                       # mirrors the package; network is disabled
```

## CI/CD

`.github/workflows/ci.yml` runs format, lint, import contracts and strict mypy; tests on Ubuntu and macOS with a 95% branch coverage gate; tests against the lowest allowed direct dependencies with all extras; a package build with a wheel smoke test, a strict docs build, pip-audit, and trivy. `.github/workflows/release.yml` builds on version tags, publishes to PyPI with Trusted Publishing when the `PUBLISH_TO_PYPI` repository variable is `true`, and deploys the docs to GitHub Pages.

## Author

Igor Lashkov — rwrotson@yandex.ru
