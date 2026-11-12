# deadwax: implementation plan and handoff journal

## Status and handoff

This is the implementation specification and multi-session handoff for deadwax. It is meant to be sufficient for an engineer or coding agent starting without the planning conversation. The original request (Russian, 2026-11-12) asked for a library and CLI that collects, for one track or album, everything open sources know about that exact recording, with four goals: (1) texts describing its sound, (2) relations for further searches, (3) confirmation of the exact recording and version with visible discrepancies, (4) streaming links.

- **Status:** Stages 0–2 complete; Stage 3 next (see the status table).
- **Branch:** `main`. Stage 0 was committed by the user as `df3befa`. Agents never create commits on the user's behalf.
- **Working rule:** complete one stage, run its acceptance checks, append dated evidence, update the status table, report an English Conventional Commit suggestion, and stop. Resume the next stage only when the user asks.
- Read `AGENTS.md` and `docs/architecture.md` (import rules R1–R9) before code changes. After code changes run `uv run poe check`; after docs or public docstring changes also run `uv run --group docs properdocs build --strict`.

### Accepted decisions

| Topic | Decision |
| --- | --- |
| Names | Distribution `deadwax`, package `deadwax`, command `deadwax`, env prefix `DEADWAX_`, error base `DeadwaxError`. |
| Entity kind | Text queries **must** state `--album` or `--track` (mutually exclusive; missing → usage error, exit 2). A URL implies its kind (Bandcamp `/album/` vs `/track/`, MB `release-group`/`recording`, Discogs `master`/`release`, Odesli entity type); a flag that contradicts the URL is a usage error. |
| Anti-bot | Full ladder: browser-like header profiles + HTTP/2 + cookies + jitter + Retry-After + challenge detection on plain httpx; optional `stealth` extra (curl_cffi TLS impersonation) and `browser` extra (Playwright Chromium) as escalation transports for HTML adapters only. Official APIs (MusicBrainz, Discogs API, Wikimedia, Last.fm, Odesli) always use an honest `deadwax/<ver> (+contact)` User-Agent, as their policies require. |
| Odesli seed | When no streaming URL is known after pass 1, the Odesli adapter seeds itself with Deezer search, then iTunes Search (open, keyless). They are internal lookups, not fact sources; only Odesli facts appear. |
| Manual check | User has Discogs token and Last.fm key (in `.env`); I choose the five records (below) and confirm them at Stage 7. |
| Language | Code, docs, plan journal, commit messages in English. |
| Git | No agent commits; stop after each stage with a Conventional Commit suggestion (AGENTS.md "Commit Handoff"). |

### Product contract

deadwax is general-purpose: output is equally useful to a person in a terminal (`--format pretty|markdown`) and to a program reading JSON. Every fact carries `source` (adapter) and `url`. Nothing is invented or "completed": no data means an empty field. A candidate with a different version is never merged into the main record; it goes to relations or is dropped, and the disagreement is recorded in identity. A failing adapter never breaks the others; it appears in `errors`.

Out of scope for v1 (listed in README as planned): Boomkat, Juno, Norman, Forced Exposure, Hard Wax, Phonica, Soundohm, Bleep, Rough Trade, AllMusic, press reviews (one generic adapter with per-site rules; RA GraphQL), Apple Music, Rate Your Music (browser only), Genius, Album of the Year, ListenBrainz, NTS, Mixcloud, SecondHandSongs, WhoSampled (ToS — not without a separate decision), 1001Tracklists/KEXP/WFMU/BBC Sounds, Spotify (search and link only), Deezer/iTunes/YouTube as fact sources, SoundCloud, Beatport/Juno Download/Traxsource. Never used: Every Noise at Once, direct Metacritic scraping (ratings come from Wikipedia), Spotify audio-features.

## Architecture

### Layers (import-linter, top → bottom)

```
deadwax.main      console script; reports missing `cli` extra
deadwax.cli       Typer app, DEADWAX_* Settings (env, .env, TOML config), rich rendering   [cli]
deadwax.logs | deadwax.sources   (independent siblings)
  logs            LogSettings, setup_logging (unchanged template)                         [logs]
  sources         adapters, HTTP stack, cache, rate limits, `lookup()` composition        base: httpx[http2], selectolax; optional: curl_cffi [stealth], playwright [browser]
deadwax.core      models, query parsing, normalization, version detection, matching,
                  merge/discrepancies, Adapter protocol, two-pass orchestrator, markdown   base: pydantic only
```

- `core` stays pydantic-only (+ stdlib asyncio/sqlite-free). The orchestrator is pure asyncio over an `Adapter` protocol, so it is testable with fake adapters.
- `sources` imports from `deadwax.core` (library internals). `cli`, `logs`, `main` import only from `deadwax`. Optional packages (`curl_cffi`, `playwright`) are imported lazily inside `deadwax.sources._http` only; `import deadwax` must not load them (extend `tests/test_package.py`).
- New contracts: core forbids `httpx`, `selectolax`, `curl_cffi`, `playwright`, `structlog`, `pydantic_settings`, `typer`, `rich`; sources forbids `structlog`, `pydantic_settings`, `typer`, `rich`; logs forbids sources' packages.

### Import rules

The normative text of rules R1–R9 is in `docs/architecture.md` ("Import rules"); contracts are in `pyproject.toml`, named after the rule. Summary: layers `main → cli → (logs | sources) → core`; `cli`/`main`/`logs` use only `deadwax`; `sources` uses only the `deadwax.core` package; adapters are independent; third-party packages are confined per layer and module; optional packages are imported lazily; per-module contracts (R4, R5, module-level R6) are added in the stage that creates the module, because import-linter fails on missing layer modules.

### Package layout

```
src/deadwax/
  __init__.py            public API: Query, EntityKind, Dossier + fact models, parse_query, lookup,
                         SourcesConfig (+ per-source settings), source_statuses, to_markdown, errors
  core/
    errors.py            DeadwaxError, InvalidQueryError(ValueError), ConfigurationError, AdapterFailure
    query.py             Query model; parse "Artist - Title" (dash variants, quoting) and URL detection
    models.py            Dossier, Identity, Tag, Credit, Text, Relation, Link, Discrepancy, AdapterError,
                         Provenance, Partial (adapter output), enums
    normalize.py         NFKC + casefold, diacritics fold for Latin only, feat./ft./with stripping,
                         punctuation/dash/quote unification, no transliteration (keeps Cyrillic/Japanese)
    versions.py          title → (base_title, VersionInfo(kind, detail)) from (), [], " - X Remix" etc.
    matching.py          artist/title match score (stdlib difflib on normalized tokens) + version gate
    merge.py             Partial[] → Dossier: dedupe by normalized key, aggregate provenance,
                         record discrepancies, route mismatched versions to relations
    adapter.py           Adapter protocol, Capability, Requirement, Pass (IDENTITY|ENRICH), LookupContext
    orchestrator.py      two passes, per-adapter timeout, TaskGroup, error capture, context propagation
    markdown.py          to_markdown(dossier)
  sources/
    config.py            SourcesConfig: http (timeout, contact, fallback ladder), cache (dir, ttl, enabled),
                         per-adapter settings (discogs.token, lastfm.api_key, enabled flags) — SecretStr
    lookup.py            lookup(query, config) -> Dossier; build_adapters(config); source_statuses(config)
    _http/
      client.py          HttpClient: one per adapter; profile (api|browser), limiter, retry, cache, ladder
      profiles.py        header profiles (honest API UA; Chrome/Firefox-consistent browser headers)
      ratelimit.py       async per-host token bucket with jitter
      retry.py           backoff with full jitter on 429/5xx/transport errors, honours Retry-After
      cache.py           stdlib sqlite3 response cache, TTL per adapter, secrets stripped from keys
      challenge.py       detect Cloudflare/captcha/“Just a moment” pages → BlockedError
      impersonate.py     curl_cffi transport (lazy import, `stealth` extra)
      browser.py         Playwright fetcher (lazy import, `browser` extra), consistent UA/locale/viewport
    _html.py             selectolax helpers, JSON-LD and OpenGraph extraction
    musicbrainz.py  odesli.py  discogs.py  bandcamp.py  lastfm.py  wikipedia.py   (one adapter each,
                         package if it grows: parse functions separated from fetch functions)
  logs/                  template, log file name deadwax.log
  cli/
    settings.py          Settings(BaseSettings): DEADWAX_ prefix, `__` nesting, .env, TOML config file
                         (default platformdirs user config dir, override DEADWAX_CONFIG_FILE / --config)
    app.py               default lookup command + `sources` subcommand
    render.py            pretty (rich), json, markdown dispatch
  main.py
```

### Data model (core/models.py)

- `Provenance(source: str, url: HttpUrl | None)` — every fact carries `sources: list[Provenance]` (merged facts accumulate).
- `Scope`: `recording | release | release_group | artist | label` — so release-specific facts rank above artist-wide ones in output.
- `Query(kind: EntityKind, artist: str | None, title: str | None, url: HttpUrl | None, ids: dict[str, str])`.
- `Identity`: canonical `artist`, `title`, `kind`, `version: VersionInfo(kind: original|remix|live|demo|remaster|cover|edit|instrumental|acoustic|alternate|unknown, detail)`, `year`, `labels: list[LabelRef(name, catno)]`, `isrcs`, `upcs`, `external_ids` (mbid, discogs_release, discogs_master, wikidata, bandcamp_id, …), `discrepancies: list[Discrepancy(field, values: list[SourcedValue])]`, `ambiguities: list[str]`. Each identity value is a sourced value.
- `Tag(name, weight: float | None, kind: genre|style|mood|tag|descriptor, scope, sources)`.
- `Credit(role, name, instruments, scope, sources)`.
- `Text(kind: review|label|shop|wiki|editorial|user, body, author, publication, date, rating: Rating(value, scale) | None, language, scope, sources)`.
- `Relation(kind: member|project|label|label_release|compilation|mix|broadcast|cover|covered_by|remix|remix_of|sample|sampled_by|similar|other_version|appears_on, target: Entity(name, artist, kind, ids, url), note, sources)`.
- `Link(service, url, target: track|album|artist|label, preview_url, sources)`.
- `AdapterError(source, status: skipped|failed|timeout|blocked|rate_limited|not_found, reason)`; `Dossier(query, identity, tags, credits, texts, relations, links, errors, generated_at)`.
- JSON is `Dossier.model_dump_json()`; schema via `Dossier.model_json_schema()` (documented). Nothing is invented: absent data → empty field.

### Adapters and orchestration

- Protocol: `name`, `capabilities: frozenset[Capability]` (identity, links, tags, credits, texts, relations), `requires: tuple[Requirement, ...]` (e.g. `discogs.token` for search), `pass_: Pass`, `async lookup(query, context) -> Partial`. `status(config)` → ready / missing key (with variable name) / disabled / missing extra.
- **Pass 1 (identity & links):** MusicBrainz, Odesli (and URL resolution for the input URL: Bandcamp page, Discogs/MB IDs, any streaming URL via Odesli). Produces `LookupContext`: canonical artist/title/version, MBIDs, Discogs IDs, Wikidata QID, Bandcamp URL, streaming URLs.
- **Pass 2 (enrichment, parallel):** Discogs, Bandcamp, Last.fm, Wikipedia — each uses context IDs/URLs first, falls back to its own search.
- Each adapter call wrapped: timeout (`--timeout`, per-adapter override), any exception → `AdapterError`, never propagates. Ctrl-C cancels cleanly.
- Matching gate: every candidate from search is scored (normalized artist + base title, version compared separately). Same work, different version → `Relation(other_version|remix|live…)` + discrepancy note, never merged into identity. Below threshold → dropped (logged at DEBUG).

### Per-adapter coverage (four goals: sound texts, relations, identity, links)

| Adapter | Access | Takes |
| --- | --- | --- |
| MusicBrainz | WS/2 JSON, 1 req/s, honest UA | search recording / release-group (Lucene, with aliases for non-Latin); recording: artist-credits, ISRCs, releases (+ compilations via secondary types), tags/genres with counts, artist-rels (producer, engineer, instrument, vocal, remixer), recording-rels (remix, DJ-mix, samples), work-rels → work's other recordings flagged cover; release-group/release: labels, catno, barcode, url-rels (Discogs, Bandcamp, Wikidata, streaming, AllMusic, review links); artist member-of rels for members/projects |
| Odesli | `api.song.link/v1-alpha.1/links`, ≤10 req/min keyless | links per platform with entity type, ISRC/UPC hints; seed: known URL → Deezer search → iTunes Search |
| Discogs | API v2, 60/min with token (25 without); token needed for search | master/release: genres+styles, extraartists credits with roles, notes, labels+catno, identifiers (barcode), tracklist positions & track-level credits; master versions (reissues/remasters → other_version); `database/search?track=&format=Compilation` → compilations; label → neighbouring releases; artist members/groups. User reviews from release HTML page via browser-profile ladder (blocked → `AdapterError(blocked)`) |
| Bandcamp | no API | page `data-tralbum` + `data-embed` + JSON-LD (`MusicAlbum`/`MusicRecording`: keywords tags, description/about, credits, datePublished, publisher label, tracks, ISRC if present); “supported by” fan blurbs → `Text(user)`; recommendations block → `similar`; label/band page → label releases. Search via `bcsearch_public_api` autocomplete endpoint, fallback HTML `/search`. Fallback: mobile `api/mobile/24/tralbum_details` JSON |
| Last.fm | API key | `track.getInfo` / `album.getInfo` (wiki summary+content, toptags with counts → weight, url), `track.getSimilar` → similar; artist tags only as `scope=artist` |
| Wikipedia / Wikidata | MediaWiki + Wikidata API, honest UA | QID from MB url-rels or `wbsearchentities`; claims: genre P136, producer P162, label P264, date P577, performer, review score P444 with reviewer P447; sitelinks → article in en + original-language wiki; `action=parse` sections Background/Recording/Composition/Critical reception → `Text(wiki)`; `{{Album ratings}}` template → ratings (Metacritic, AllMusic, AOTY…) |

Rate limits/TTL defaults per adapter in `sources/config.py`; all overridable.

### HTTP stack details

- One `httpx.AsyncClient` per adapter host group, HTTP/2, connection limits, timeouts.
- Ladder for `browser` profile requests (HTML adapters): httpx → curl_cffi impersonate (if `stealth` installed and enabled) → Playwright (if `browser` installed and enabled, `playwright install chromium` documented) when `challenge.py` detects a block or 403/503 with challenge markers. Setting `DEADWAX_HTTP__ESCALATION=none|impersonate|browser` (default: highest available).
- Politeness: per-host token bucket, jittered spacing, `Retry-After`, bounded retries (default 3), response size cap, cache first. No robots.txt bypass of disallowed API paths used by APIs; HTML pages fetched only for the specific release.
- Cache: sqlite3 at platformdirs user cache dir (CLI) or caller-provided path (library; default disabled when no path). Key = adapter + method + URL + sorted params minus secrets. TTL per adapter (default 7 days, 404 → 1 day, errors never cached). `--no-cache` bypasses read and write.

### CLI

- `deadwax [OPTIONS] QUERY` where QUERY is `"Artist - Title"` or a URL. Options: `--album/--track`, `--sources a,b`, `--exclude a,b`, `--format pretty|json|markdown`, `--no-cache`, `--timeout SECONDS`, `--config PATH`, `--verbose`, `--version`. Implemented as Typer app with `sources` subcommand plus default lookup (callback with `invoke_without_command` or a `lookup` command aliased as default — chosen at Stage 4 after checking Typer's behaviour; `deadwax sources` must not be parsed as a query).
- `deadwax sources`: table of adapters, pass, capabilities, status (ready / missing `DEADWAX_LASTFM__API_KEY` / disabled / missing extra `deadwax[browser]`).
- pretty: rich sections Identity (with discrepancies highlighted), Tags, Credits, Texts (release-scope first, truncated with source/url), Relations grouped by kind, Links, Errors; every fact shows its sources.
- Exit codes: 0 dossier with identity; 3 nothing matched; 2 usage/config error; 1 unexpected.
- Settings: `DEADWAX_HTTP__*`, `DEADWAX_CACHE__*`, `DEADWAX_DISCOGS__TOKEN`, `DEADWAX_LASTFM__API_KEY`, `DEADWAX_<SOURCE>__ENABLED`, `DEADWAX_LOG__*`. Precedence: CLI flags > env > `.env` > TOML config > defaults. Every field described and listed in `.env.example` (existing tests enforce).

## Dependencies

- base: `pydantic`, `httpx[http2]`, `selectolax`.
- extras: `logs` = structlog; `cli` = `deadwax[logs]`, pydantic-settings, typer, rich, platformdirs; `stealth` = curl_cffi; `browser` = playwright.
- dev group additionally: all extra packages (for tests/mypy), `pytest-asyncio`, `pytest-socket`.
- Added via `uv add` with current versions; verify Python 3.14 wheels (selectolax, curl_cffi, playwright) at Stage 0 and record observations.

## Testing strategy

- Network off: `pytest-socket` (`--disable-socket --allow-unix-socket` for xdist). Adapters get their HTTP client injected; tests use `httpx.MockTransport` serving recorded fixtures from `tests/fixtures/<source>/` (JSON/HTML, secrets scrubbed).
- `scripts/record_fixtures.py` (dev-only, not packaged) fetches live responses for the five check records + edge cases and stores them; rerunnable.
- Coverage targets: query parsing; normalization (Cyrillic, Japanese, diacritics, feat.); version detection; matching original vs remix vs live vs remaster; merge/provenance/discrepancies; orchestrator (two passes, context propagation, timeout, exception, blocked, missing key, `--sources/--exclude`); each adapter's parsers on fixtures; HTTP stack (retry/backoff on 429/5xx with fake clock, Retry-After, rate limiter, cache TTL & secret stripping, challenge detection, ladder escalation with fake transports — no real curl_cffi/Playwright in CI); CLI formats and exit codes via Typer `CliRunner`; import-time behaviour.
- 95% branch coverage kept.

## Implementation stages and acceptance criteria

| Stage | Status | Deliverable |
| --- | --- | --- |
| 0 | Complete | Template renamed to deadwax, dependencies, import rules R1–R9 and contracts, docs adapted, this journal. |
| 1 | Complete | Core: errors, models, query parsing, normalization, version detection, matching, merge, markdown. |
| 2 | Complete | Adapter protocol, two-pass orchestrator; HTTP stack: profiles, rate limiter, retry, cache, challenge detection, escalation ladder. |
| 3 | Not started | MusicBrainz and Odesli (Deezer/iTunes seed), URL resolution, recorded fixtures. |
| 4 | Not started | CLI: lookup and `sources`, formats, settings with TOML config, cache directory; first manual run. |
| 5 | Not started | Bandcamp and Discogs (reviews through the escalation ladder). |
| 6 | Not started | Last.fm and Wikipedia/Wikidata. |
| 7 | Not started | README source tiers, docs, full checks, manual runs on five records, final report. |

### Stage 0: establish the workstream

- [x] Rename `my_lib`/`my-lib`/`MY_LIB_`/`MyLibError` to `deadwax`/`DEADWAX_`/`DeadwaxError`; remove the `greet` example; project metadata, URLs, docs site name.
- [x] Add base, extra and dev dependencies through uv; verify Python 3.14 wheels.
- [x] Write import rules R1–R9 into `docs/architecture.md` and AGENTS.md; encode them as import-linter contracts over the existing packages and empty `core`, `sources`, `sources/_http`.
- [x] Extend the import-time test to every optional package; disable sockets in tests; configure pytest-asyncio.
- [x] Create this journal.

**Acceptance:** `poe check` and the strict docs build pass; contracts are verified to catch a violation. **Suggested message:** `chore: rename template to deadwax and define import rules`.

### Stage 1: core model and matching

- [x] `errors` (extend if needed), `query` (Query, EntityKind, `parse_query` with dash variants and quoting; URL kind detection for Bandcamp, MusicBrainz, Discogs; kind mismatch → `InvalidQueryError`).
- [x] `models`: Provenance, Scope, Identity with sourced values, Tag, Credit, Text, Rating, Relation, Entity, Link, Discrepancy, AdapterError, Partial, Dossier; JSON round-trip.
- [x] `normalize` (NFKC, casefold, Latin diacritics, feat./ft., punctuation and dashes; Cyrillic and Japanese preserved), `versions` (remix, live, demo, remaster, cover, edit, instrumental, acoustic, alternate; detail such as remixer).
- [x] `matching` (artist and base title score, version gate), `merge` (dedupe, provenance aggregation, discrepancies, other versions to relations), `markdown`.
- [x] R5 layers contract for core modules; public exports; reference index rows.

**Acceptance:** tests cover Unicode variants, feat., bracketed versions, original vs remix vs live vs remaster, discrepancy recording, no merge on title alone; `poe check` green. **Suggested message:** `feat(core): add dossier model, query parsing and version-aware matching`.

### Stage 2: orchestration and HTTP stack

- [x] `adapter` protocol (name, capabilities, requires, pass, lookup, status) and `LookupContext`; `orchestrator` with two passes, per-adapter timeout, error capture, include/exclude.
- [x] `sources.config`, `_http` client with API and browser header profiles, per-host rate limiter, retry with jittered backoff and Retry-After, sqlite cache with TTL and secret stripping, challenge detection, curl_cffi and Playwright transports behind lazy imports.
- [x] R4 and module-level R6 contracts for the new modules.

**Acceptance:** fake-adapter tests for pass ordering, context propagation, timeout, exception, blocked, missing key; HTTP tests with MockTransport and fake clock; escalation tested with fake transports only. **Suggested message:** `feat(sources): add adapter orchestration and resilient HTTP stack`.

### Stage 3: identity and links adapters

- [ ] MusicBrainz (search, recording, release-group, release, work, artist relations); Odesli with Deezer then iTunes seed; input URL resolution.
- [ ] `scripts/record_fixtures.py`; fixtures for the check records and edge cases.
- [ ] `lookup()` composition and `source_statuses()` exported from `deadwax`.

**Acceptance:** parser tests on fixtures for all four goals the adapters serve; lookup integration test over MockTransport. **Suggested message:** `feat(sources): add MusicBrainz and Odesli adapters`.

### Stage 4: command line

- [ ] Default lookup with `--album/--track`, `--sources`, `--exclude`, `--format`, `--no-cache`, `--timeout`, `--config`; `deadwax sources`.
- [ ] Settings for HTTP, cache, credentials, per-source enable flags; TOML config source; `.env.example`; rich pretty renderer; exit codes.
- [ ] First live manual run recorded here.

**Acceptance:** CliRunner tests for every option, format and exit code; settings tests; docs build. **Suggested message:** `feat(cli): add lookup and sources commands`.

### Stage 5: Bandcamp and Discogs

- [ ] Bandcamp: data-tralbum, data-embed, JSON-LD, supported-by, recommendations, label page, search API with HTML fallback, mobile API fallback.
- [ ] Discogs: master, release, versions, compilations search, label releases, artist members, reviews through the escalation ladder.

**Acceptance:** fixture tests for every extraction path, missing token behaviour, blocked page. **Suggested message:** `feat(sources): add Bandcamp and Discogs adapters`.

### Stage 6: Last.fm and Wikipedia

- [ ] Last.fm track and album info, tags with weights, similar tracks; missing key → skipped.
- [ ] Wikidata claims and review scores; Wikipedia sections and the album ratings template, in English and the original language.

**Acceptance:** fixture tests including a non-English article. **Suggested message:** `feat(sources): add Last.fm and Wikipedia adapters`.

### Stage 7: qualification and documentation

- [ ] README source tables by tier with "planned" marks and caveats; docs pages for sources and output schema.
- [ ] Full checks, package build and wheel smoke, audit.
- [ ] Manual runs on the five records with `--format pretty`; final report separating mock-tested from live-verified behaviour.

**Acceptance:** all checks pass or blocked ones have precise reasons; outputs reviewed against source pages. **Suggested message:** `docs: document sources and qualify deadwax v1`.

### Five manual-check records (proposed; confirmed at Stage 7)

1. Mainstream: `--track "Radiohead - Paranoid Android"`.
2. Bandcamp-only underground: chosen at Stage 7 by checking that Odesli/Deezer/iTunes find nothing besides Bandcamp; queried by Bandcamp URL and by text.
3. Electronic on a small label: `--album "Huerco S. - For Those of You Who Have Never (And Also Those Who Have)"` (Proibito).
4. Non-English: `--track "Кино - Группа крови"` (and a Japanese fallback such as `--album "細野晴臣 - Hosono House"` if Cyrillic coverage is thin).
5. Known remix: `--track "Everything but the Girl - Missing (Todd Terry Remix)"` — must not merge with the 1994 original; the original appears as `remix_of`.

## Verification

- `uv sync --all-groups --locked`, `uv run poe check` (fmt-check, lint, lint-imports, mypy strict, pytest with 95% branch coverage), `uv run --group docs properdocs build --strict`, `uv build` + wheel smoke (base import without extras; `deadwax --help` with `cli`), `uv run poe audit`.
- Manual: `deadwax sources`; the five records in `--format pretty` (plus one `--format json` validated against `Dossier`), with `--no-cache` first run and a cached second run; one forced adapter failure (`--timeout 0.01`) to show `errors`; report real outputs, separating mock-tested from live-verified behaviour.

## Risks

| Risk | Handling |
| --- | --- |
| Scraped markup / undocumented endpoints change (Bandcamp, Discogs HTML) | Multiple extraction paths per page (data attributes, JSON-LD, mobile API); parse failures → `AdapterError`, fixtures re-recordable. |
| Bot protection on Discogs HTML | Ladder; otherwise explicit `blocked` error, never partial guesses. |
| Python 3.14 wheels missing for an optional dep | Record at Stage 0; extra declared with a marker or deferred, core unaffected. |
| Ambiguous identity (same title, several artists/versions) | Matching gate + `ambiguities`/`discrepancies`; never merge on title alone. |
| Rate limits (Odesli 10/min, MB 1/s) | Per-host limiter + cache; rate-limited → `AdapterError(rate_limited)`. |

## Progress evidence and decision log

Update the stage table only after its acceptance gate passes. Append dated evidence under the newest entry: what changed, exact commands and outcomes, what remains. Do not replace old evidence. Keep decisions distinct from observations.

| Date | Decision | Reason | Affected stage |
| --- | --- | --- | --- |
| 2026-11-12 | Text queries require `--album` or `--track`. | Explicit user choice. | 1, 4 |
| 2026-11-12 | Escalation ladder httpx → curl_cffi → Playwright for HTML pages; honest UA for APIs. | Explicit user choice; API policies. | 2, 5 |
| 2026-11-12 | Odesli seeded by Deezer, then iTunes Search. | Explicit user choice. | 3 |
| 2026-11-12 | Import rules R1–R9 fixed before code; per-module contracts added with modules. | User request; import-linter rejects missing layer modules. | All |
| 2026-11-12 | Fact URLs are plain strings, not `HttpUrl`. | `HttpUrl` rewrites URLs (trailing slash), which breaks deduplication and shows sources differently from the page. | 1 |
| 2026-11-12 | `Query.kind` may be `None` for a URL whose kind the URL does not reveal; the resolver adapter sets it. Text queries still require it. | Odesli and custom Bandcamp domains reveal the type only after a request. | 1, 3 |
| 2026-11-12 | Relation kinds are directional (`cover_of`/`covered_by`, `remix_of`/`remixed_by`, `samples`/`sampled_by`); `VersionKind` adds `reissue` (deluxe/expanded/anniversary editions). | Direction is needed to tell an original from its cover or remix. | 1 |
| 2026-11-12 | A candidate with a different version is kept out of the dossier: its facts are dropped, it becomes an `other_version` relation, and the disagreement is a `version` discrepancy. An unrelated candidate becomes a `no_match` error. For a URL query, the first candidate (the URL's own page) is the reference, so the orchestrator must run the URL resolver first. | Request: versions must not mix, and disagreements must be shown. | 1, 2 |
| 2026-11-12 | `InvalidInputError` replaced by `InvalidQueryError`; `ConfigurationError` added in Stage 0. | Needed by the import-rule text (R7) and the CLI from the start. | 0, 1 |
| 2026-11-12 | `SourceError` with `BlockedError`, `RateLimitedError`, `NotFoundError` lives in `core.errors`; the orchestrator maps them to `ErrorKind`. | Adapters and the HTTP stack raise them; `errors` is the lowest core layer, so the mapping sits in the orchestrator. | 2 |
| 2026-11-12 | Adapters are constructed with their settings and report `status()` without arguments; `requires` lists setting paths (`discogs.token`) that the CLI maps to `DEADWAX_` names. | Keeps core free of configuration types. | 2, 4 |
| 2026-11-12 | Pass 2 context is the identity and links of a merge of pass-1 results; a URL query's resolver runs alone first and gives its kind to a kindless query. | Rejected other-version candidates must not leak IDs into enrichment. | 2 |
| 2026-11-12 | Excluded and disabled adapters produce no error; adapters missing a key or extra produce `skipped`; unknown names in include/exclude raise `ConfigurationError`. | Errors report what the user did not choose. | 2, 4 |
| 2026-11-12 | Default API contact is the repository URL, not a personal address; overridable by `http.contact`. | API policies need a contact; no personal data by default. | 2 |
| 2026-11-12 | Plain httpx transport lives in `_http.plain`; a layers contract ("R8: HTTP stack modules") orders `_http` modules. | R8 requires a layers contract for every multi-module package. | 2 |
| 2026-11-12 | Captcha widget markers count as a challenge only on 403/429/503; Cloudflare interstitial markers count on any status. | Ordinary pages embed reCAPTCHA in login forms. | 2, 5 |

**Current task:** Stage 2 complete. **Next action:** user review and commit; then Stage 3 on request.

### 2026-11-12 — Stage 2 qualification

Core: `errors` gained `SourceError` (with `url`) and `BlockedError`, `RateLimitedError`, `NotFoundError`. `adapter` defines `Pass`, `Capability`, `Requirement`, `SourceState`, `SourceStatus`, `LookupContext` (query, identity, links; `id()` and `urls()` helpers), and the `Adapter` protocol (`name`, `pass_`, `capabilities`, `requires`, `status()`, `resolves()`, `lookup()`). `orchestrator.run(query, adapters, LookupOptions, now=)` selects adapters (include/exclude, status), runs a URL resolver alone first, then the identity pass and the enrichment pass concurrently with `TaskGroup`, each adapter under `asyncio.timeout`; failures become `AdapterError`s (timeout, blocked, rate_limited, not_found, failed with a logged traceback) and cancellation propagates. The R5 contract now includes `orchestrator` and `adapter`.

Sources: `config` has `HttpSettings`, `CacheSettings`, `SourceSettings`, `DiscogsSettings.token`/`LastfmSettings.api_key` (`SecretStr`), `Escalation`, `SourcesConfig` with per-source rate and TTL defaults. `_http`: `messages` (`Request`, `Response`, `Fetcher`, `TransportError`, `ResponseTooLargeError`), `profiles` (honest `deadwax/<version> (+contact)` API headers; Chrome and Firefox header sets), `ratelimit` (per-host token bucket with jitter, injectable clock/sleep/rng), `retry` (full-jitter backoff, Retry-After seconds and dates, cap → `RateLimitedError`), `challenge` (Cloudflare, DataDome, PerimeterX, captcha markers), `cache` (sqlite3 via `asyncio.to_thread`, key without secret params, 2xx with source TTL, 404 with `not_found_ttl`, broken cache counts as empty), `plain` (httpx with HTTP/2, cookies, streamed size cap), `impersonate` (curl_cffi `AsyncSession(impersonate="chrome")`), `browser` (Playwright Chromium, status of the last main-frame navigation, waits up to 5 s for network idle), and `client` (`HttpClient(ClientSpec, SourcesConfig, HttpResources)`: cache → limiter → retries → challenge check → escalation for browser-profile clients, sticky per client; secret params removed from response and error URLs). Contracts added: R4 (`_http`, `config`), R8 HTTP stack layers, R6 curl_cffi only in `_http.impersonate`, R6 Playwright only in `_http.browser`. A temporary probe (`_http/_probe.py` importing curl_cffi and playwright, `config` importing `_http`) broke all four as intended and was removed.

Checks: `uv run poe check` passed (Ruff format and lint, 13 contracts kept, mypy strict on 66 files, 290 tests, 99.94% branch coverage); `uv run --group docs properdocs build --strict` passed. Everything is mock-tested only: HTTP through `httpx.MockTransport`, curl_cffi and Playwright through fake modules in `sys.modules`; no live request was made and no real browser was launched. No commit was created.

### 2026-11-12 — Stage 1 qualification

Added the core modules: `query` (`Query`, `EntityKind`, `IdKind`, `parse_query`, `recognize_url` for Bandcamp, MusicBrainz, Discogs, Spotify, Deezer, and Apple Music URLs; dash variants and quotes; kind required for text and checked against the URL), `models` (provenance, scopes, identity with sourced values, tags, credits, texts with ratings, relations, links, adapter errors, `RecordCandidate`, `Partial`, `Dossier`), `normalize` (NFKC, casefold, dash and quote folding, diacritics removed from Latin letters only, `feat.` splitting, artist keys without a leading "The", ISRC/catalog and barcode keys), `versions` (bracketed and dash-suffix markers; exact forms such as "Original Mix" and "Radio Edit" first, then keywords by priority remix > live > demo > cover > instrumental > acoustic > edit > alternate > reissue > remaster), `matching` (difflib character and sorted-word similarity, thresholds 0.85, collaboration credits 0.9, remix and live details compared, album and track never match, title alone never matches), `merge` (reference record, verdicts, consensus with discrepancies for artist, title, version, date and IDs, deduplicated facts with combined provenance, scope-ordered output), and `markdown`. `deadwax.core` exports all of them for `sources`; `deadwax` exports the models, `parse_query`, `parse_title`, and `to_markdown`. The R5 layers contract covers the seven modules (`orchestrator` and `adapter` join in Stage 2).

Checks: `uv run poe check` passed (Ruff, 9 contracts kept, mypy strict on 39 files, 175 tests, 99% branch coverage; all core modules at 100%); `uv run --group docs properdocs build --strict` passed. No network was used, no live source was queried, and no commit was created.

### 2026-11-12 — Stage 0 qualification

Renamed the template package, distribution, command, environment prefix and error base to `deadwax`/`DEADWAX_`/`DeadwaxError` across sources, tests, docs, CI, and properdocs; removed the `greet` example and its command and tests. The CLI now has only the root callback (`--version`, `--verbose`, help when no command). Core errors: `DeadwaxError`, `InvalidQueryError` (`ValueError`), `ConfigurationError`. Empty packages `deadwax.sources` and `deadwax.sources._http` exist so contracts apply from the start. README, AGENTS.md, `docs/architecture.md` (import rules R1–R9), `docs/getting_started.md`, `docs/notes.md` (template renaming section removed), and the reference index describe deadwax. CI: the lowest job installs all extras; the wheel smoke test runs `deadwax --version`.

Dependencies added with `uv add` (versions resolved on 2026-11-12): base `httpx[http2]>=0.28.1`, `selectolax>=1.0.2`; `cli` adds `rich>=15.0.0`, `platformdirs>=4.12.4`; `stealth` = `curl-cffi>=0.17.0`; `browser` = `playwright>=1.65.1`; dev adds those plus `pytest-asyncio>=1.5.0`, `pytest-socket>=0.8.1`. All installed on CPython 3.14.8 (macOS) from wheels. Lower bounds are the current releases; the CI `lowest` job will show whether they can be widened.

import-linter observations: eight contracts kept. A temporary module `deadwax/sources/_probe.py` importing `deadwax.core.errors` broke the R3 wildcard contract (`deadwax.core.*`) as intended and was removed. Adding a nonexistent layer (`deadwax.nonexistent`) fails with `Missing layer ... does not exist`, so R4/R5 contracts are added with their modules. pytest runs with `--disable-socket --allow-unix-socket` under xdist without issues; pytest-asyncio is in strict mode.

Checks: `uv sync --all-groups --locked` passed; `uv run poe check` passed (Ruff format and lint, 8 contracts kept, mypy strict on 25 files, 45 tests, 99.32% branch coverage); `uv run --group docs properdocs build --strict` passed after README links to repository files were made absolute (the docs home page includes README); `uv build` produced sdist and wheel; wheel smoke: base install imports without optional packages, `deadwax` without extras exits 1 naming `deadwax[cli]`, `deadwax --version` with the `cli` extra prints `deadwax 0.1.0`; `git diff --check` passed. Not run: pre-commit hooks (they rewrite files), `poe audit`, macOS/Ubuntu CI. No commit was created.

## Resume instructions

> Read `AGENTS.md`, `docs/architecture.md`, and `DEADWAX_PLAN.md`. Inspect the branch, worktree, stage table, and latest evidence. Implement the first incomplete stage only, preserving accepted decisions and import rules. Run the stage checks, append dated evidence, update the status only when acceptance passes, report an English commit message, stop at the stage boundary, and do not create commits.

Distinguish planned, implemented, mock-tested, and live-verified behaviour in every handoff.
