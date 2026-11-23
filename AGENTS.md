# AGENTS.md

deadwax is a typed Python library and command that, for one track, album, artist, or label, collects what open sources know about it: texts describing its sound, credits, relations for further digging, version identity with discrepancies between sources, and listening links. Every fact carries its source and URL; nothing is invented.

The base install depends on Pydantic, httpx, and selectolax. Extras: `logs` (structlog), `cli` (Typer, Pydantic Settings, rich, platformdirs), `stealth` (curl_cffi), `browser`/`patchright` (Patchright), `nodriver` (Nodriver). Distribution, package, and command `deadwax`; environment prefix `DEADWAX_`.

## Workflow

- Implementation is staged. Read `DEADWAX_PLAN.md` (specification and handoff journal) before work, implement only the first incomplete stage, append dated evidence, and stop at the stage boundary.
- Inspect `git status` before editing. Preserve existing uncommitted changes and limit edits to the requested task.
- Run `uv run poe check` after code changes; after docs, `properdocs.yml`, or public docstring changes also run the strict docs build.
- Report which checks ran, which were skipped, and why. `poe test-fast` is not the full CI suite.

## Commit Handoff

- Do not create or amend commits on the user's behalf.
- After completing and verifying a meaningful, self-contained part of the work, pause before starting the next part.
- At each pause, send the user a one-line English Conventional Commit message for the completed work. Resume when the user asks you to continue.

## Python formatting

- In new or edited code, keep function signatures, calls, and collection literals on one line when they fit. When they need wrapping, put one parameter, argument, or item on each line. Add a trailing comma after the last entry when there are two or more entries so Ruff preserves the layout.
- Omit optional trailing commas in single-entry forms. Keep the required comma in a single-element tuple and any comma Ruff inserts in a wrapped signature with one parameter.

## Commands

```bash
uv sync --all-groups --locked
uv run poe check        # fmt-check, lint, lint-imports, typecheck, test (95% branch coverage)
uv run poe quick        # lint, lint-imports, typecheck (no tests)
uv run poe test-fast    # pytest without coverage
uv run poe test-live    # opt-in live lookups in tests/integration (network, keys from .env)
uv run poe fmt          # ruff format (rewrites files)
uv run --group docs properdocs build --strict
```

## Layers

```
main     src/deadwax/main.py   console script; reports a missing `cli` extra
cli      src/deadwax/cli/      Typer app, DEADWAX_* Settings, rendering, composition root
logs     src/deadwax/logs/     LogSettings, setup_logging(), run journal
sources  src/deadwax/sources/  adapter packages, HTTP stack, Deadwax client, lookup()
core     src/deadwax/core/     models, matching, merge, orchestrator, errors (Pydantic only)
```

A layer imports only layers below it; `logs` and `sources` are siblings. Import rules R1–R9 are in `docs/architecture.md`; `uv run poe lint-imports` enforces most of them.

## Invariants

- Do not lower coverage thresholds, disable checks, relax import-linter contracts, or add lint and type suppressions solely to pass CI. Explain necessary suppressions at the affected line.
- Tests never use the network, except `tests/integration/` under `--live`.
- Importing `deadwax` performs no I/O, reads no environment, configures no logging, and imports no optional dependency.
- Library code never reads the environment or `.env`; only `load_settings()` in the CLI does.
- A failing source adapter never raises out of a lookup; its failure is recorded in the dossier's `errors`.
- Expected failures raise a `DeadwaxError` subclass.
- Everything in `deadwax.__all__` is public API; mark removals and incompatible changes with `!` or a `BREAKING CHANGE:` footer.
- Keep the user's `.env` and secrets untracked.
- Code, docs, comments, and commit messages are in English.

## Read when

Before editing, read the guide for each affected layer and the test guide if the change touches tests.

| Task | Read |
| --- | --- |
| Any code change | `docs/architecture.md` (layers, R1–R9, lookup flow, errors) |
| Working in `src/deadwax/core/` | [Core guide](docs/agents/src/deadwax/core.md) |
| Working in `src/deadwax/cli/` | [CLI guide](docs/agents/src/deadwax/cli.md) |
| Working in `src/deadwax/logs/` | [Logging guide](docs/agents/src/deadwax/logs.md) |
| Working in `src/deadwax/sources/` | [Sources guide](docs/agents/src/deadwax/sources.md) |
| Adding or changing a source | [Adding a source](docs/architecture.md#adding-a-source) |
| Working in `tests/` | [Test guide](docs/agents/tests.md) |
| Dependencies, settings, credentials, public API, docstrings and comments | `CONTRIBUTING.md` |
| CI, releases, publishing | README "CI/CD", `docs/notes.md` |
| History, or changing a v1/v2 adapter | `plans/v1.md`, `plans/v2.md` (archived stages and decision logs) |
