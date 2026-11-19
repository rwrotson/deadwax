# Getting Started

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

## Installation

```bash
git clone <repo-url>
cd deadwax
uv sync --all-groups --locked
uv run pre-commit install
```

`pre-commit install` sets up three Git hooks:

- `pre-commit` — file hygiene checks, `uv lock` check, actionlint, a check that `.gitignore` hides no source files, ruff (with `--fix`), import-linter, mypy
- `commit-msg` — Conventional Commit format (Commitizen)
- `pre-push` — pytest without coverage

Ruff and mypy run from the locked project environment (`uv run --no-sync`), so hook and CI versions match.

## Using the Command

```bash
deadwax --track "Radiohead - Paranoid Android"          # pretty output in the terminal
deadwax https://open.spotify.com/track/6LgJvl0Xdtc73RJ1mmpotq
deadwax --album "Huerco S. - For Those of You Who Have Never (And Also Those Who Have)" --format json
deadwax --track "Кино - Группа крови" --sources musicbrainz --no-cache
deadwax sources                                          # what each source contributes and whether it can run
deadwax runs                                             # journaled runs; deadwax runs ID shows one run's timeline
```

A text query must state `--album` or `--track`; a URL implies its kind. Options: `--sources` and `--exclude` (comma-separated names), `--facets` (kinds of facts), `--isrc CODE` (the track's ISRC), `--format pretty|json|markdown`, `--no-cache`, `--timeout SECONDS` per source, `--config PATH` (TOML), `--verbose` or `--debug` for diagnostic stderr logs. Normal runs print the dossier and its error summary without logs. Settings come from flags, `DEADWAX_*` variables, `.env`, and a TOML file, in that order of precedence; see [Configuration](configuration.md).

[Sources](sources.md) describes what each source contributes and needs; [Output](output.md) describes the dossier and its errors.

| Exit code | Meaning |
|-----------|---------|
| 0 | A source identified the record |
| 1 | Unexpected error |
| 2 | Usage or configuration error |
| 3 | Nothing matched the query |

## Using the Library

```python
import asyncio

from deadwax import EntityKind, LookupConfig, lookup, parse_query

query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)
dossier = asyncio.run(lookup(query, LookupConfig()))
print(dossier.model_dump_json(indent=2))
```

For many lookups, keep one `Deadwax` client and ask for the facts you need with a `Request`; see [Requests](requests.md).

The library never reads the environment and caches nothing unless `LookupConfig.cache.path` is set. A failing source never raises out of `lookup()`; it appears in `dossier.errors`. Library errors derive from `DeadwaxError`.

A base install (`pip install deadwax`) depends on Pydantic, httpx, and selectolax. Optional extras add application features:

| Extra | Adds |
|-------|------|
| `deadwax[logs]` | `deadwax.logs`: `LogSettings` and `setup_logging()` (structlog) |
| `deadwax[cli]` | The `deadwax` command (Typer, Pydantic Settings, rich, platformdirs) and the `logs` extra |
| `deadwax[stealth]` | curl_cffi transport for pages behind bot protection |
| `deadwax[browser]` or `deadwax[patchright]` | Patchright transport; run `patchright install chromium` once |
| `deadwax[nodriver]` | Nodriver transport; install Chrome separately |

Configure logging in the application, or use the bundled helper:

```python
from deadwax.logs import LogSettings, setup_logging

setup_logging(LogSettings(level="DEBUG"))
```

## Development Commands

Tasks are available via [poethepoet](https://poethepoet.natn.io/) — run with `uv run poe <name>`:

```bash
uv run poe check        # fmt-check, lint, lint-imports, typecheck, test
uv run poe fmt          # ruff format .
uv run poe fmt-check    # ruff format --check .
uv run poe lint         # ruff check .
uv run poe lint-imports # import-linter layer contracts
uv run poe typecheck    # mypy (strict: src, tests, docs)
uv run poe test         # pytest (parallel, 95% branch coverage enforced)
uv run poe test-fast    # pytest without coverage, parallel, random order
uv run poe test-live    # opt-in live lookups in tests/integration (network, sequential, keys from .env)
uv run poe docs         # properdocs serve
uv run poe audit        # pip-audit over locked dependencies
```

Tests run in parallel and in random order. pytest-randomly prints the seed at the top of the run; reproduce an order-dependent failure with `uv run pytest -p randomly --randomly-seed=<seed>`. `poe test-fast` skips coverage; `poe check` runs the same quality and test steps as the CI `quality` and `test` jobs.

Or run the tools directly:

```bash
uv run pytest                        # full suite without coverage
uv run pytest --cov                  # with the coverage gate
uv run pytest tests/path/to/test.py  # single file
uv build                             # sdist and wheel in dist/
```

## Versioning & Changelog

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) — enforced by the `commit-msg` pre-commit hook.

```bash
uv run cz bump            # bump version, update CHANGELOG, create tag
git push origin main --tags
uv run cz changelog       # update CHANGELOG without bumping
uv run cz changelog --dry-run
```

Bump type is inferred from commits: `fix:` → patch · `feat:` → minor · `feat!:` / `BREAKING CHANGE:` → major (minor while the version is `0.x`). `cz bump` creates the tag locally; pushing it runs the release workflow, which deploys the docs and, when `PUBLISH_TO_PYPI` is enabled, publishes to PyPI.

## Adding Functionality

Follow the layers and import rules in the [architecture guide](architecture.md):

1. Put the code in the layer that owns it (`core/` for models and matching, `sources/` for adapters and HTTP) and raise a `DeadwaxError` subclass for expected failures.
2. Add a new module to the layer contract of its package in `pyproject.toml` (rules R4 and R5).
3. Export supported names from the package `__init__.py` and from `deadwax/__init__.py`, with `__all__`.
4. Test it in the mirrored directory under `tests/`, with recorded responses instead of network access, and list the module in `docs/reference/index.md`.

## Configuration

The `deadwax` command reads `DEADWAX_*` environment variables and a `.env` file in the working directory through `deadwax.cli.settings.load_settings()`; the library itself never reads them. Sections are nested with `__`:

| Prefix | Controls |
|--------|----------|
| `DEADWAX_LOG__*` | Log levels, console renderer, optional log directory, file rotation |

```env
DEADWAX_LOG__LEVEL=DEBUG
DEADWAX_LOG__FORMAT=json
```

All variables are listed on the [configuration page](configuration.md).
