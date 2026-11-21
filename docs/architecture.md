# Architecture

The core models a query and its dossier, matches and merges facts, and runs adapters; it knows nothing about HTTP, web services, settings loading, logging setup, or the command line. `sources` implements one adapter package per source, the service catalogue, per-source settings, and the HTTP stack on top of the core. Each outer layer adds one application concern, and its third-party packages come from an optional extra.

## Layers

Layers are listed from top to bottom. A layer may import any layer below it and never one above it. `logs` and `sources` are independent siblings.

| Layer | Location | Responsibility | Third-party packages | Install |
| --- | --- | --- | --- | --- |
| Entry point | `deadwax/main.py` | `deadwax` console script; reports a missing `cli` extra | — | base |
| CLI | `deadwax/cli/` | Composition root: loads `DEADWAX_*` settings, sets up logging, calls the library, renders output, maps errors to exit codes | Pydantic Settings, Typer, rich, platformdirs | `deadwax[cli]` |
| Logging setup | `deadwax/logs/` | `LogSettings`, the opt-in `setup_logging()`, and the run journal (`run_journal()`) for applications | structlog | `deadwax[logs]` |
| Sources | `deadwax/sources/` | Adapter packages and their registry, per-source settings (`LookupConfig`), service catalogue and URL queries (`parse_query`), HTTP stack (rate limits, retries, cache, escalation), the `Deadwax` client and `lookup()` | httpx, selectolax; curl_cffi, Patchright, Nodriver | base; `deadwax[stealth]`, `deadwax[browser]`, `deadwax[nodriver]` |
| Core | `deadwax/core/` | Models, text queries and generic URL rules, normalization, matching, merge, adapter protocol, orchestrator, requests and trimming to them, adapter deadline, trace events, `DeadwaxError` hierarchy | Pydantic | base |

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
deadwax.sources.lookup                  `lookup()` with a client for one call; `describe_sources()`
deadwax.sources.client                  `Deadwax`: shared HTTP resources, adapters built and run per lookup
deadwax.sources.registry                `ADAPTERS` in resolver order and `build_adapters`
deadwax.sources.adapters                one package per source
deadwax.sources._search                 search keys, search hits, `SearchPageAdapter`, `track_on_release`
deadwax.sources._adapter | _html        `HttpAdapter` and its default `resolves()` | HTML and JSON-LD helpers
deadwax.sources.services                service catalogue: hosts and URL rules; URL queries and `parse_query`
deadwax.sources._http                   `HttpClient`, built from the resolved `ClientSettings` of its source
deadwax.sources.config                  `LookupConfig`; one settings class per source holding its defaults
```

Each source has one settings class in `config` (rate, HTML transports, browser mode, credentials) and one field in `PerSourceSettings`; `tests/sources/test_registry.py` checks that the fields and `ADAPTERS` name the same sources. `LookupConfig.client_settings(name)` resolves a source's settings over the shared `http` and `cache` sections for its `HttpClient`.

Every adapter is a package `deadwax.sources.adapters.<name>`, named after its source, with the modules `adapter` (the adapter class and its requests), `parse` (pure functions from responses to facts), and optionally `models` (Pydantic models of JSON responses), layered in that order (contract "R4: adapter package modules"). Its tests live in `tests/sources/adapters/<name>/` and its recorded responses in `tests/fixtures/<name>/`.

Every adapter declares `service`: the name of the catalogue service whose pages it reads, or `None`. The default `resolves()` takes a query URL of that service; adapters that resolve by recognized identifiers override it. The core knows no services: it matches a URL against rules it is given (`recognize_url`) and parses text queries (`text_query`).

Adapters are independent (contract "R4: adapters are independent"): they never import each other, and data found by one adapter reaches another only through `LookupContext`. A helper needed by two adapters moves down into `_search`, `_adapter`, `services`, `_html`, or `_http`.

Inside `deadwax.sources._http` (contract "R4: HTTP stack modules"), from top to bottom:

```
client
sessions
impersonate | browser | nodriver | plain | cache
challenge | profiles | ratelimit | retry | messages
```

### R5. Inside `core` (contract)

From top to bottom:

```
orchestrator | select
request
adapter | merge
matching
versions
normalize
models
query
errors | events | deadline
```

`events` holds `TraceEvent`, `trace()`, and `trace_scope()`, which every other core module may use. An event name is a `TraceEvent` member; a new event is added to the enum and to the table in `docs/runs.md`. `deadline` holds the adapter time budget that the orchestrator sets and adapters read or pause. `request` defines what an application asks for; `select` trims a merged dossier to it.

A change to this order is recorded in the progress evidence of `DEADWAX_PLAN.md`.

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

curl_cffi, Patchright, and Nodriver are imported inside the function that needs them; a missing package raises `ConfigurationError` naming the extra. Type-only references go under `if TYPE_CHECKING:`. `import deadwax` does not load structlog, Pydantic Settings, Typer, rich, platformdirs, curl_cffi, Patchright, or Nodriver; `tests/test_package.py` checks this in a fresh interpreter. `deadwax` imports `deadwax.sources` on first use of one of its names (`lookup`, `LookupConfig`, …), because httpx loads rich and click at import time whenever they are installed.

### R8. Style (Ruff and review)

- Absolute `deadwax.` imports. Relative imports only in `__init__.py` re-exports of sibling modules (`from .module import Name`, never `..`).
- Every re-exporting `__init__.py` defines `__all__`; no `import *`.
- Import names (`from deadwax.core import Dossier`), except stdlib and third-party packages conventionally used as namespaces (`import asyncio`, `import httpx`).
- A module or package whose name starts with `_` is imported only from its parent package and that package's subpackages.
- Import order: stdlib, third-party, first-party.
- Every package with more than one module has a layers contract, so imports cannot form cycles.

### R9. Code outside the package

Tests may import internal modules to test them; CLI tests go through `deadwax.cli.app`. `docs/` scripts import only `deadwax` and `deadwax.cli.settings`. Development scripts in `scripts/` import only `deadwax` and `deadwax.sources`.

## Lookup flow

1. A `Deadwax` client (`sources/client.py`) opens the cache, the per-host rate limiters, and the shared browser sessions for its whole life; `deadwax.lookup(request, config)` opens one for a single call. For each lookup, `registry.build_adapters` constructs every adapter of `ADAPTERS` with its settings section; each builds its `HttpClient` from `LookupConfig.client_settings(name)` on first use.
2. A query is one of `TrackQuery`, `AlbumQuery`, `ArtistQuery`, `LabelQuery`, or `UnresolvedQuery` (a URL whose kind only a resolver finds), told apart by `kind`. The orchestrator (`core/orchestrator.py`) selects adapters from `include`, `exclude`, the default set, the record kind of the query, and the request's facets (see [Requests](requests.md)); disabled ones and those that do not look up the query's kind produce no error, adapters without a key or extra are `skipped`, and when no selected adapter looks up the query's kind the dossier has one `unsupported` error.
3. For a URL query, the first adapter whose `resolves()` accepts it and that has a lookup for the query's kind (`unresolved` when the URL does not reveal it) runs alone and its candidate becomes the reference; a URL whose kind only a request reveals becomes the typed query of the kind it found (`with_kind`).
4. The remaining adapters run pass by pass (`identity`, `enrich`, `links`), concurrently within a pass up to `concurrency`, each under its time budget (`core/deadline.py`). Each pass receives a `LookupContext` with the identity, links, and review links of a merge of the earlier passes. The context's query is promoted to the kind known so far (the query's, else the merged identity's), and `Lookups.bind` picks the slot typed by that query; an adapter without that slot sits the pass out.
5. `merge` passes every partial through the matching gate: tracks and albums compare by `RecordKey` (a candidate of another version becomes an `other_version` relation and a `version` discrepancy), artists and labels by `NameKey` (shared identifiers, else the name); an unrelated candidate, or one of another family, is a `no_match` error. The identity is a `RecordIdentity`, `ArtistIdentity`, or `LabelIdentity` by the kind found. The result is the `Dossier`; a `blocked` error gets the adapter's access description, and `select.trim` keeps only the requested facts.

Each step emits `TraceEvent` events through `trace()`; the run journal (`deadwax.logs.run_journal`) records them.

## Adding a source

1. A settings class in `sources/config.py` with the source's defaults (rate, HTML transports, browser mode, credentials) and a field in `PerSourceSettings`.
2. A package `sources/adapters/<name>/` with `adapter`, `parse`, and optionally `models`; the adapter declares `name`, `group`, `pass_`, `service`, and `requires`, and returns from `lookups` one lookup per record kind it supports (`track`, `album`, `artist`, `label`, and `unresolved` for a query whose kind it can find itself), each typed by its query; an unset slot means the source does not look that kind up. An HTML source that searches and reads one page builds on `SearchPageAdapter`, whose default slots share one search.
3. The service's hosts and URL rules in `sources/services.py` when the adapter reads its own pages.
4. An entry in `ADAPTERS` (`sources/registry.py`), in resolver order.
5. Recorded responses in `tests/fixtures/<name>/`, tests in `tests/sources/adapters/<name>/`, a line per setting in `.env.example`, a credentials section in README when it needs one, and the source in `docs/sources.md` and the README tables.

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
