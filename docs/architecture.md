# Architecture

The core models a query and its dossier, matches and merges facts, and runs adapters; it knows nothing about HTTP, settings loading, logging setup, or the command line. `sources` implements adapters and the HTTP stack on top of the core. Each outer layer adds one application concern, and its third-party packages come from an optional extra.

## Layers

Layers are listed from top to bottom. A layer may import any layer below it and never one above it. `logs` and `sources` are independent siblings.

| Layer | Location | Responsibility | Third-party packages | Install |
| --- | --- | --- | --- | --- |
| Entry point | `deadwax/main.py` | `deadwax` console script; reports a missing `cli` extra | — | base |
| CLI | `deadwax/cli/` | Composition root: loads `DEADWAX_*` settings, sets up logging, calls the library, renders output, maps errors to exit codes | Pydantic Settings, Typer, rich, platformdirs | `deadwax[cli]` |
| Logging setup | `deadwax/logs/` | `LogSettings`, the opt-in `setup_logging()`, and the run journal (`run_journal()`) for applications | structlog | `deadwax[logs]` |
| Sources | `deadwax/sources/` | Adapters, HTTP stack (rate limits, retries, cache, escalation), `lookup()` | httpx, selectolax; curl_cffi, Patchright, Nodriver | base; `deadwax[stealth]`, `deadwax[browser]`, `deadwax[nodriver]` |
| Core | `deadwax/core/` | Models, query parsing, normalization, matching, merge, adapter protocol, orchestrator, `DeadwaxError` hierarchy | Pydantic | base |

`deadwax/__init__.py` re-exports the supported names with `__all__` and attaches a `NullHandler` to the `deadwax` logger. `deadwax.logs` raises a `ModuleNotFoundError` that names the `logs` extra when structlog is missing.

## Import rules

import-linter enforces the rules marked *contract* with `uv run poe lint-imports`; the contracts are in `pyproject.toml` and named after the rule. Other rules are checked by Ruff or in review.

### R1. Layer order (contract)

`main → cli → (logs | sources) → core`. A layer imports only layers below it; `logs` and `sources` never import each other.

### R2. API surfaces

- `deadwax` (`deadwax/__init__.py`, `__all__`) is the public API covered by semantic versioning.
- The `deadwax.core` package (`core/__init__.py`, `__all__`) is the core's surface for the library's own outer code. It is a superset of what `deadwax` re-exports.
- All other modules are internal.

### R3. Who imports what (contract)

| Importer | May import | Must not import |
| --- | --- | --- |
| `main` | `deadwax.cli.app`, lazily inside `main()`; stdlib | other `deadwax` modules |
| `cli` | `deadwax` public names, `deadwax.logs`, `deadwax.cli.*` | `deadwax.core`, `deadwax.sources` |
| `logs` | `deadwax` public names, `deadwax.logs.*` | `deadwax.core`, `deadwax.sources` |
| `sources` | the `deadwax.core` package, `deadwax.sources.*` within R4 | `deadwax.core.<module>` |
| `core` | `deadwax.core.*` within R5 | any other `deadwax` layer |

### R4. Inside `sources` (contract)

From top to bottom:

```
deadwax.sources.lookup                  composition: builds adapters and runs the orchestrator
deadwax.sources.adapters                one package per source
deadwax.sources._search                 search keys, search hits, `SearchPageAdapter`, `track_on_release`
deadwax.sources._adapter | services | _html   `HttpAdapter` | service names of URLs | HTML and JSON-LD helpers
deadwax.sources._http
deadwax.sources.config
```

Every adapter is a package `deadwax.sources.adapters.<name>`, named after its source, with the modules `adapter` (the adapter class and its requests), `parse` (pure functions from responses to facts), and optionally `models` (Pydantic models of JSON responses), layered in that order (contract "R4: adapter package modules"). Its tests live in `tests/sources/adapters/<name>/` and its recorded responses in `tests/fixtures/<name>/`.

Adapters are independent (contract "R4: adapters are independent"): they never import each other, and data found by one adapter reaches another only through `LookupContext`. A helper needed by two adapters moves down into `_search`, `_adapter`, `services`, `_html`, or `_http`.

Inside `deadwax.sources._http` (contract "R8: HTTP stack modules"), from top to bottom:

```
client
sessions
impersonate | browser | nodriver | plain | cache
challenge | profiles | ratelimit | retry | messages
```

### R5. Inside `core` (contract)

From top to bottom:

```
orchestrator
adapter | merge | markdown
matching
versions
normalize
models
query
errors | events
```

`events` holds `trace()` and `trace_scope()`, which every other core module may use.

A change to this order is recorded in the decision log of `DEADWAX_PLAN.md`.

### R6. Third-party packages (contract)

| Package | Allowed only in |
| --- | --- |
| pydantic | every layer |
| httpx, selectolax | `deadwax.sources` |
| curl_cffi | `deadwax.sources._http.impersonate` |
| patchright | `deadwax.sources._http.browser` |
| nodriver | `deadwax.sources._http.nodriver` |
| structlog | `deadwax.logs` |
| pydantic_settings, platformdirs | `deadwax.cli.settings` |
| typer | `deadwax.cli` |
| rich | `deadwax.cli.render` |

Transitive dependencies (anyio, h2, httpcore, click, and others) are never imported directly; add a package as a direct dependency before importing it.

### R7. Lazy optional imports

curl_cffi, Patchright, and Nodriver are imported inside the function that needs them; a missing package raises `ConfigurationError` naming the extra. Type-only references go under `if TYPE_CHECKING:`. `import deadwax` does not load structlog, Pydantic Settings, Typer, rich, platformdirs, curl_cffi, Patchright, or Nodriver; `tests/test_package.py` checks this in a fresh interpreter. `deadwax` imports `deadwax.sources` on first use of one of its names (`lookup`, `SourcesConfig`, …), because httpx loads rich and click at import time whenever they are installed.

### R8. Style (Ruff and review)

- Absolute `deadwax.` imports. Relative imports only in `__init__.py` re-exports of sibling modules (`from .module import Name`, never `..`).
- Every re-exporting `__init__.py` defines `__all__`; no `import *`.
- Import names (`from deadwax.core import Dossier`), except stdlib and third-party packages conventionally used as namespaces (`import asyncio`, `import httpx`).
- A module or package whose name starts with `_` is imported only from its parent package and that package's subpackages.
- Import order: stdlib, third-party, first-party.
- Every package with more than one module has a layers contract, so imports cannot form cycles.

### R9. Code outside the package

Tests may import internal modules to test them; CLI tests go through `deadwax.cli.app`. `docs/` scripts import only `deadwax` and `deadwax.cli.settings`. Development scripts in `scripts/` import only `deadwax` and `deadwax.sources`.

## Public API

Everything listed in `deadwax.__all__` is public and follows semantic versioning. Other modules can be imported but are not covered by compatibility guarantees, except `deadwax.logs`, which applications use for setup. The `deadwax` command and its `DEADWAX_*` variables are a separate interface for end users. A removal or incompatible change to the public API is a breaking change (`feat!:` or a `BREAKING CHANGE:` footer).

## Import-time behaviour

`import deadwax` does not read the environment or `.env`, configure logging or structlog, add handlers outside the `deadwax` logger, import optional dependencies, create HTTP clients, or perform I/O.

## Configuration

The library never reads the environment or `.env`. Only the CLI does, in `deadwax.cli.settings`; another application builds the library's settings objects itself and passes them as arguments.

## Logging

Library modules log through `logging.getLogger(__name__)`. The `NullHandler` on `deadwax` keeps records silent until the application configures logging, and records then follow the application's levels and handlers.

`deadwax.logs.setup_logging()` is a helper for applications that do not have their own setup:

1. Without arguments it uses the `LogSettings` defaults; it never reads the environment.
2. It creates all handlers first; if one fails, the previous configuration stays in place.
3. It replaces the handlers it created before and keeps all others.
4. It adds a stderr handler (console or JSON) and, when a log directory is set, a rotating JSON file handler.
5. It configures structlog to render through the same stdlib handlers, so structlog and stdlib records share one format.

The `deadwax` command calls it with `LogSettings` loaded from `DEADWAX_LOG__*`.

## Errors

| Error | Base classes | Raised when |
| --- | --- | --- |
| `DeadwaxError` | `Exception` | Base for every expected library failure |
| `InvalidQueryError` | `DeadwaxError`, `ValueError` | The query cannot be parsed or is inconsistent |
| `ConfigurationError` | `DeadwaxError` | A setting, credential, or optional dependency required for an operation is missing |
| `SourceError` | `DeadwaxError` | A source could not answer a request; carries the request URL without secrets |
| `BlockedError` | `SourceError` | Every allowed transport met an anti-bot challenge |
| `RateLimitedError` | `SourceError` | The source kept answering 429 or asked to wait too long |
| `NotFoundError` | `SourceError` | The source has no page for the request (HTTP 404) |

Callers can catch `DeadwaxError` for all library failures or the built-in base for a specific one. Add a subclass for each new kind of expected failure. Unexpected exceptions are not wrapped. A failing adapter does not raise out of a lookup; its failure is recorded in the dossier.
