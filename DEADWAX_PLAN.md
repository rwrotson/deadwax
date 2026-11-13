# deadwax: implementation plan and handoff journal

## Status and handoff

This is the implementation specification and multi-session handoff for deadwax. It is meant to be sufficient for an engineer or coding agent starting without the planning conversation. The original request (Russian, 2026-11-12) asked for a library and CLI that collects, for one track or album, everything open sources know about that exact recording, with four goals: (1) texts describing its sound, (2) relations for further searches, (3) confirmation of the exact recording and version with visible discrepancies, (4) streaming links.

- **Status:** Stages 0–7 complete; v1 qualified (see the status table).
- **Branch:** `main`. Stage 0 was committed by the user as `df3befa`. Agents never create commits on the user's behalf.
- **Working rule:** complete one stage, run its acceptance checks, append dated evidence, update the status table, report an English Conventional Commit suggestion, and stop. Resume the next stage only when the user asks.
- Read `AGENTS.md` and `docs/architecture.md` (import rules R1–R9) before code changes. After code changes run `uv run poe check`; after docs or public docstring changes also run `uv run --group docs properdocs build --strict`.

### Accepted decisions

| Topic | Decision |
| --- | --- |
| Names | Distribution `deadwax`, package `deadwax`, command `deadwax`, env prefix `DEADWAX_`, error base `DeadwaxError`. |
| Entity kind | Text queries **must** state `--album` or `--track` (mutually exclusive; missing → usage error, exit 2). A URL implies its kind (Bandcamp `/album/` vs `/track/`, MB `release-group`/`recording`, Discogs `master`/`release`, Odesli entity type); a flag that contradicts the URL is a usage error. |
| Anti-bot | Full ladder: browser-like header profiles + HTTP/2 + cookies + jitter + Retry-After + challenge detection on plain httpx; optional `stealth` extra (curl_cffi TLS impersonation) and `browser` extra (Playwright Chromium) as escalation transports for HTML adapters only. Official APIs (MusicBrainz, Discogs API, Wikimedia, Last.fm, Odesli) always use an honest `deadwax/<ver> (+contact)` User-Agent, as their policies require. |
| Streaming links | Superseded on 2026-11-12 (Odesli retired its keyless API): links come from MusicBrainz URL relations, an iTunes Search adapter, and a keyless Deezer adapter; Odesli runs only with `odesli.api_key`. See the decision log. |
| Manual check | User has Discogs token and Last.fm key (in `.env`); I choose the five records (below) and confirm them at Stage 7. |
| Language | Code, docs, plan journal, commit messages in English. |
| Git | No agent commits; stop after each stage with a Conventional Commit suggestion (AGENTS.md "Commit Handoff"). |

### Product contract

deadwax is general-purpose: output is equally useful to a person in a terminal (`--format pretty|markdown`) and to a program reading JSON. Every fact carries `source` (adapter) and `url`. Nothing is invented or "completed": no data means an empty field. A candidate with a different version is never merged into the main record; it goes to relations or is dropped, and the disagreement is recorded in identity. A failing adapter never breaks the others; it appears in `errors`.

Out of scope for v1 (listed in README as planned): Boomkat, Juno, Norman, Forced Exposure, Hard Wax, Phonica, Soundohm, Bleep, Rough Trade, AllMusic, press reviews (one generic adapter with per-site rules; RA GraphQL), Apple Music, Rate Your Music (browser only), Genius, Album of the Year, ListenBrainz, NTS, Mixcloud, SecondHandSongs, WhoSampled (ToS — not without a separate decision), 1001Tracklists/KEXP/WFMU/BBC Sounds, Spotify (search and link only), YouTube as a fact source, SoundCloud, Beatport/Juno Download/Traxsource. Never used: Every Noise at Once, direct Metacritic scraping (ratings come from Wikipedia), Spotify audio-features.

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
| iTunes Search | keyless `itunes.apple.com/search` and `/lookup`, ~20 req/min | Apple Music track, album and artist links with previews, release date, genre; looks up the Apple Music link MusicBrainz curates before searching; resolves Apple Music URLs |
| Deezer | keyless `api.deezer.com` | track by ISRC or album by barcode from pass 1, else search; links, previews, ISRC, barcode, label, genres; resolves Deezer URLs; refused (Akamai) from the development network |
| Odesli | `api.song.link/v1-alpha.1/links`, API key required since 2026-07-31 | links on every platform, seeded by the query URL or a streaming link found in pass 1; skipped without `odesli.api_key` |
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
| 3 | Complete | MusicBrainz, iTunes, Deezer, Odesli (key only), URL resolution, recorded fixtures, `lookup()`. |
| 4 | Complete | CLI: lookup and `sources`, formats, settings with TOML config, cache directory; first manual run. |
| 5 | Complete | Bandcamp and Discogs (reviews through the escalation ladder). |
| 6 | Complete | Last.fm and Wikipedia/Wikidata; Odesli reads the song.link page. |
| 7 | Complete | README source tiers, docs, full checks, manual runs on five records, final report. |

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

- [x] MusicBrainz (search, recording, release-group, release, work, artist relations); ~~Odesli with Deezer then iTunes seed~~ iTunes and Deezer adapters, Odesli with an API key only; input URL resolution.
- [x] `scripts/record_fixtures.py`; fixtures for the check records and edge cases.
- [x] `lookup()` composition and ~~`source_statuses()`~~ `describe_sources()` exported from `deadwax`.

**Acceptance:** parser tests on fixtures for all four goals the adapters serve; lookup integration test over MockTransport. **Suggested message:** `feat(sources): add MusicBrainz and Odesli adapters`.

### Stage 4: command line

- [x] Default lookup with `--album/--track`, `--sources`, `--exclude`, `--format`, `--no-cache`, `--timeout`, `--config`; `deadwax sources`.
- [x] Settings for HTTP, cache, credentials, per-source enable flags; TOML config source; `.env.example`; rich pretty renderer; exit codes.
- [x] First live manual run recorded here.

**Acceptance:** CliRunner tests for every option, format and exit code; settings tests; docs build. **Suggested message:** `feat(cli): add lookup and sources commands`.

### Stage 5: Bandcamp and Discogs

- [x] Bandcamp: data-tralbum, data-embed, JSON-LD, supported-by, recommendations, label page, search API with HTML fallback, mobile API fallback.
- [x] Discogs: master, release, versions, compilations search, label releases, artist members, reviews through the escalation ladder.

**Acceptance:** fixture tests for every extraction path, missing token behaviour, blocked page. **Suggested message:** `feat(sources): add Bandcamp and Discogs adapters`.

### Stage 6: Last.fm and Wikipedia

- [x] Last.fm track and album info, tags with weights, similar tracks; missing key → skipped.
- [x] Wikidata claims and review scores; Wikipedia sections and the album ratings template, in English and the original language.
- [x] Odesli from the song.link page instead of the retired API (added during the stage at the user's request).

**Acceptance:** fixture tests including a non-English article. **Suggested message:** `feat(sources): add Last.fm and Wikipedia adapters`.

### Stage 7: qualification and documentation

- [x] README source tables by tier with "planned" marks and caveats; docs pages for sources and output schema.
- [x] Full checks, package build and wheel smoke, audit.
- [x] Manual runs on the five records with `--format pretty`; final report separating mock-tested from live-verified behaviour.

**Acceptance:** all checks pass or blocked ones have precise reasons; outputs reviewed against source pages. **Suggested message:** `docs: document sources and qualify deadwax v1`.

### Five manual-check records (confirmed at Stage 7)

1. Mainstream: `--track "Radiohead - Paranoid Android"`.
2. Bandcamp-only underground: `--album "ESTADO DE BIENESTAR - Capítulo IV : La Fiesta Seria y Nuevas Formas de Tecnaco"` (Oráculo Records, 2026), also by `https://oraculorecords.bandcamp.com/album/cap-tulo-iv-la-fiesta-seria-y-nuevas-formas-de-tecnaco`; MusicBrainz, iTunes, Discogs, and Wikipedia know nothing of it and Odesli has no seed (Deezer is refused from the development network).
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
| 2026-11-12 | Odesli is no longer the link backbone: MusicBrainz URL relations, an iTunes Search adapter, and a keyless Deezer adapter provide links and resolve their URLs; Odesli needs `odesli.api_key` and is skipped without it. Supersedes "Odesli seeded by Deezer, then iTunes". | Linktree retired the keyless song.link API on 2026-07-31 (`401 PUBLIC_API_ACCESS_DEPRECATED`, verified live); user choice. | 3 |
| 2026-11-12 | iTunes and Deezer contribute facts (candidate, links, genre, ISRC, barcode) like other adapters, so the matching gate drops a store result for another version. | Their results must pass the same version check as everything else. | 3 |
| 2026-11-12 | MusicBrainz track search: official album/EP/single releases first (`status:official AND primarytype:(album OR single OR ep)`), then a plain search, then the same with the title's base; candidates ranked by appearing on such a release, year, and number of releases; DJ-mix excerpts and videos excluded. | A plain search returned 25 equal-score live and bootleg recordings without the original; partial dates sorted before full ones. | 3 |
| 2026-11-12 | MusicBrainz disambiguation comments set a version only for live, demo, instrumental, acoustic, remix, edit, remaster, alternate; "original mix"/"album version" mean original. | Comments are free text ("“Amplified Heart” album original mix"). | 3 |
| 2026-11-12 | A non-original recording relates to its work as `remix_of`/`cover_of`/`other_version`; only an original lists the work's covers. Release IDs and the Discogs master of a track are those of its first release; its Wikidata ID is the song's (from the work). | MusicBrainz often lacks a direct remix relation; IDs of a track's album are needed by later adapters. | 3, 5, 6 |
| 2026-11-12 | `describe_sources()` returns `SourceInfo` (pass, capabilities, requirements, status) instead of `source_statuses()`. | The `sources` command needs more than the status. | 3, 4 |
| 2026-11-12 | Shared adapter code lives in `sources/_base.py` (R4 layer below the adapters); MusicBrainz is a package with its own layers contract. | R4 forbids adapters importing each other. | 3 |
| 2026-11-12 | `deadwax` imports `deadwax.sources` lazily (module `__getattr__`). | httpx loads rich and click at import time when installed, which broke the import-time rule. | 3 |
| 2026-11-12 | Retry backoff base is a setting (`http.retry_base`, default 1 s). | MusicBrainz answered "server busy" 503 through four 0.5 s-based retries from the shared development IP. | 3 |
| 2026-11-12 | The Typer group runs `lookup` when the first argument is not a subcommand or a root option (`--help`, `--version`); every other option belongs to `lookup` or `sources`, so `deadwax --track Q`, `deadwax URL` and `deadwax sources` all work. | A query argument on the group callback would swallow `sources`; Typer 0.29 vendors click, so the override uses `typer.Context` with a commented `type: ignore[override]`. | 4 |
| 2026-11-12 | Settings precedence: flags (init kwargs, deep-merged) > environment > `.env` > TOML (`--config`, `DEADWAX_CONFIG_FILE`, or `config.toml` in the platformdirs user config dir) > defaults. An explicitly named file must exist. `DEADWAX_CONFIG_FILE` is honoured from the process environment only. | Plan requirement; the TOML path must be known before settings load. | 4 |
| 2026-11-12 | The CLI exposes every `SourcesConfig` section, including the planned Discogs, Bandcamp, Last.fm and Wikipedia settings (marked in `.env.example` as having no effect yet). | Stable variable names before the adapters land. | 4–6 |
| 2026-11-12 | Pretty output groups tags into one line per scope and kind; JSON and Markdown keep every tag with its weight. httpx and httpcore loggers are set to WARNING unless `--verbose`. | Paranoid Android has 70+ single-vote MusicBrainz tags; httpx logs every request at INFO. | 4 |
| 2026-11-12 | `--timeout` sets the per-source lookup timeout (`adapter_timeout`), not the HTTP request timeout. `deadwax sources` also prints JSON and Markdown. | The plan's forced-failure check uses `--timeout 0.01`; programs need the source list too. | 4 |
| 2026-11-12 | Non-Latin names are compared as written; a store listing "Кино" as "Kino" yields `no_match`. Alias-aware matching is a later, separate change. | No transliteration (Stage 1 decision); MusicBrainz aliases are not yet carried in the context. | 3+ |
| 2026-11-12 | Every source has a `user_agent` setting; Discogs defaults to httpx's own (`python-httpx/<version>`), the other API sources keep `deadwax/<version> (+contact)`, Bandcamp the browser profile. | Discogs answered 403 to every User-Agent naming deadwax (`deadwax/0.1.0`, with and without `(+URL)`, `DeadwaxClient/0.1 +URL`) and 200 to `curl/8.7.1` and `python-httpx/0.28.1` from the same network (checked by the user); user choice. | 5 |
| 2026-11-12 | Discogs is ready without a token: it reads records by the Discogs IDs earlier passes found, at 25 requests a minute; search and compilations need `discogs.token`, and a lookup that would need search returns a `skipped` error. `deadwax sources` shows `ready; set DEADWAX_DISCOGS__TOKEN for search and compilations`. | MusicBrainz gives Discogs masters for most records; Discogs' anonymous limit is 25/min. | 5 |
| 2026-11-12 | Discogs reviews come from the release page through the browser profile and the ladder; a refused page (or a missing escalation browser) adds a `blocked`/`failed` error with a `reviews:` reason and keeps every API fact. Reviews are read from JSON-LD `review` entries. | The page answered 403 to plain httpx; its markup could not be inspected, so the parser follows schema.org and is not live-verified. | 5 |
| 2026-11-12 | Discogs' "Not On Label" placeholder (and catalog number "none") is not a label, and placeholder aliases ("Unknown") are not relations; " (2)" disambiguation suffixes are removed from names. | Kino's release is self-released; the old code would have listed the placeholder's catalog of unrelated releases. | 5 |
| 2026-11-12 | Bandcamp reads the page (`data-tralbum`, `data-embed`, JSON-LD, recommendations) and also the mobile `tralbum_details` API, which alone names the label; the mobile API is also the fallback when a page is blocked. The label's `/music` page is read only when that label is the selling account. | Neither markup nor JSON-LD tells a label account from an artist account (`label-band-selector` is on every page); the publisher of Huerco S.'s album is the artist's personal account. | 5 |
| 2026-11-12 | Bandcamp's HTML search runs only when the search endpoint fails, not when it finds nothing; the HTML search page is behind a Fastly "Client Challenge" (marker `/_fs-ch-` added to challenge detection). | A search without results reported `blocked` instead of `not_found`. | 5 |
| 2026-11-12 | A Bandcamp track whose album has another artist (a compilation or third-party upload) contributes only identity, links, its own credits and notes, and a `compilation` relation; the album's tags, recommendations, fan texts, date, label, and seller are dropped. | The Todd Terry remix was found on an unofficial compilation whose SEO tags and 2007 date entered the dossier and a date discrepancy. | 5 |
| 2026-11-12 | Fixtures are recorded in a hybrid mode: existing MusicBrainz, iTunes and Deezer fixtures are replayed and only Bandcamp and Discogs are recorded live (`--live` chooses); requests with a body are keyed with a body hash; recording and source tests run with `escalation=none`. | Keeps Stage 3 fixtures stable; Bandcamp search is a POST to one URL; curl_cffi opens sockets pytest-socket cannot block. | 5 |
| 2026-11-13 | Odesli reads the song.link web page (`https://song.link/<streaming URL>`, browser profile and the escalation ladder) instead of the API: the page's `__NEXT_DATA__` holds the entity (title, artist, ISRC or UPC) and a link per platform; platforms without a URL are unmatched. `OdesliSettings` and `odesli.api_key` are removed (breaking); Odesli is ready without a key, at 0.5 requests a second. Supersedes the 2026-11-12 "Odesli runs only with `odesli.api_key`". | Odesli has no public API any more (checked by the user); user choice. Verified live on 2026-11-13: Paranoid Android 10 platforms with ISRC, OK Computer 9 with UPC, an unknown Spotify ID redirects to `/not-found` (no page data → not found). | 6 |
| 2026-11-13 | The fixture recorder passes the Discogs token and the Last.fm key only to sources recorded live. | A replayed source with a credential makes requests its fixtures lack. | 6 |
| 2026-11-13 | Scores without review text (ratings templates, Wikidata P444) are `Text(kind=review, body="")` with publication and rating; such texts are deduplicated by publication, rating, and title and rendered as one line. | No separate model; a score is a review reduced to its rating. | 6 |
| 2026-11-13 | Wikidata names come in the item's original language (P407 → P424), then `mul`, then English; genres and publications in English first. A performer is named by the label or alias that matches the expected artist. | Кино stays Cyrillic; Radiohead has only a `mul` label; Huerco S. is an alias of the item "Pendant". | 6 |
| 2026-11-13 | Wikipedia reads the English article and the original-language one: the lead and h2 sections whose headings match per-language allow-lists (en, ru, ja, de, fr; other languages give the lead); a sitelink that redirects (a song's link to its album) is skipped. Song items contribute no MusicBrainz release group or Discogs master (they name the single); "part of" (P361) counts only when it is an album. | Section names differ per wiki; Q4150791's en sitelink redirects to the album article; Kino's album P361 is a list item. | 6 |
| 2026-11-13 | Last.fm errors inside 200 bodies: 6 → not found, 29 → rate limited, others → failed. Artist-wide tags have `scope=artist`, but merge deduplicates tags by name, so an artist tag equal to a track tag joins the track tag. | Last.fm reports errors in the body; merge behaviour unchanged. | 6 |
| 2026-11-13 | Odesli is seeded only by streaming links of the query or the identity pass; records whose identity-pass links name no streaming service (Huerco S., the Todd Terry remix, the OK Computer Discogs URL) report `not_found`. | Odesli runs in the enrichment pass, which sees only identity-pass links. | 6 |
| 2026-11-13 | Wikipedia prose joins text nodes without a separator, and paragraphs inside a quoted block are read once, through the block. | Live Stage 7 run: links produced spaces before punctuation (`" Paranoid Android " is`), and a wrapped pull quote appeared twice. | 6, 7 |
| 2026-11-13 | The output schema page is generated from `Dossier.model_json_schema()` (`docs/gen_schema_page.py`); `docs/sources.md` and `docs/output.md` describe sources and the dossier. | Generated pages are never edited by hand; the README holds the tier tables. | 7 |
| 2026-11-13 | With `http.escalation` unset, an escalation step that cannot run (the `browser` extra without Chromium) ends the ladder for that client: the page is `blocked` with the transports tried and `browser unavailable: … playwright install chromium`. An explicitly chosen step that cannot run stays a `ConfigurationError` (Discogs reviews: `failed`). Supersedes the Stage 5 "a missing escalation browser adds a `failed` error". | "Unset" is documented as the strongest available step; a missing browser binary is the user's setup, not a source failure. User choice. | 2, 5, 7 |
| 2026-11-13 | Blocked results are cached: a marker entry (status 403, reserved header `x-deadwax-blocked` with the reason) for `cache.blocked_ttl` (default 1 day, `0` disables); a hit raises `BlockedError("… (cached)")` without a request. Supersedes "errors never cached" for blocks only. | Every cached run climbed the Discogs review ladder again (7–10 s instead of about 1 s); fewer requests to sites that refuse us. User choice. | 2, 7 |
| 2026-11-13 | `poe test-live` loads `.env` (`envfile = { optional = [".env"] }`); the live tests pass the Last.fm key as well as the Discogs token. | Last.fm was `skipped` in every live test. User choice. | 7 |
| 2026-11-12 | Tracks from the user's library are not fixtures but opt-in live integration tests (`tests/integration`, collected only with `--live`, `poe test-live`) that check invariants and print a report. | ~25–30 MB of fixtures otherwise; live data changes; user choice. | 5, 7 |
| 2026-11-13 | Odesli runs in a third pass, `Pass.LINKS`, after enrichment. | Its seed is a streaming URL; when MusicBrainz has none, the Apple Music or Deezer link comes from iTunes or Deezer in the enrichment pass, which Odesli used to run beside. Live: "Billie Ray Martin - Planet of the Blue" gave `odesli not_found`. | post-v1 |

**Current task:** post-v1 work chosen by the user: Odesli links pass (done), then a per-source `proxy` setting. **Next action:** user review and commit of the links pass; then the proxy setting.

### 2026-11-13 — Post-v1: Odesli links pass

`Pass.LINKS` added to `core.adapter`; `orchestrator.run` runs it after the enrichment pass; `OdesliAdapter.pass_` is `LINKS`. Odesli fixtures recorded live for `huerco_s`, `missing_remix`, `bandcamp_url`, `discogs_url` (`scripts/record_fixtures.py --live odesli`; other sources replayed, existing fixtures unchanged). Tests: orchestrator links pass sees enrichment links; Odesli adapter pass; the Huerco S. lookup has Odesli links and no Odesli error. Docs: lookup flow in `docs/sources.md`, README Odesli caveat, reference index.

Live, "Billie Ray Martin - Planet of the Blue" `--no-cache`: Odesli seeded from the iTunes track URL added Deezer, Tidal, Amazon, Pandora, Napster, and store links; remaining errors Deezer and Discogs reviews `blocked` (network), Wikipedia `not_found` (no item). Observation: song.link's page for Apple track 5027215 (original) links Apple track 5027223 ("Planet of the Blue - Instrum"); the upstream page mixes versions and Odesli links carry only its provenance.

### 2026-11-13 — Stage 7 follow-up

Closed the three open items of the Stage 7 qualification (decisions above):
- `HttpClient._fetch` with `escalation` unset drops a step that raises `ConfigurationError` (`_drop_step`: the step and stronger ones are removed for the client, its fetcher closed) and raises `BlockedError` naming the transports that answered and `<step> unavailable: <reason>`. An explicit setting re-raises the error.
- `HttpClient.request` stores a blocked marker for `cache.blocked_ttl` (new `CacheSettings` field, `.env.example`, generated configuration page) and raises `BlockedError("… (cached)")` on a hit.
- `poe test-live` became a table task with an optional `.env`; `tests/integration/test_library.py` passes `DEADWAX_LASTFM__API_KEY`.
- Docs: escalation and cache in `docs/sources.md`, `blocked` row in `docs/output.md`, `test-live` lines in README, Getting Started, AGENTS.md.
- Tests: five new client tests (unavailable step at creation and at first use, explicit step, blocked cache and expiry, zero TTL); `_http/client.py` at 100% branch coverage.

Checks: `uv run poe check` passed (Ruff format and lint, 18 contracts kept, mypy strict on 122 files, 549 tests, 99.23% branch coverage); `uv run --group docs properdocs build --strict` passed.

Live, without Chromium:
- Paranoid Android `--no-cache`: exit 0 in 16.4 s, Discogs `blocked … (tried httpx, impersonate; browser unavailable: Chromium for Playwright is not installed: run 'playwright install chromium')`.
- The following cached run: 0.6 s, Deezer and Discogs `… (cached)` (a `--no-cache` run does not write, so the first cached run after it still fetches).
- `uv run poe test-live`: 22 passed in 4 min 17 s. Last.fm contributed to every track, including three that no other source finds (Ilya Vlasenko, Jeff Buckley "Sky Blue Skin", the Basinski remix); Discogs reports `blocked`, never `failed`.

Then `uv run playwright install chromium` (Chrome Headless Shell 158, 100 MiB, approved by the user): Paranoid Android and Huerco S. with `--no-cache` give Discogs `blocked … (tried httpx, impersonate, browser)`. Cloudflare refuses headless Chromium too, so the browser step is now live-verified as running, and Discogs reviews remain unavailable from this network. No commit was created.

### 2026-11-13 — Stage 7 qualification

Documentation: README "Sources" split into tier tables (tier 1 identity and links, tier 2 enrichment) with status and caveat columns, a "Planned" table grouped by kind (shops, reviews and press, catalogues, radio and mixes, streaming and stores, WhoSampled pending a ToS decision) and the never-used list; status note and project structure updated. New pages: `docs/sources.md` (lookup flow, tiers, one section per source with access, credentials, how it finds the record, contributions and limits; escalation ladder), `docs/output.md` (provenance, identity, version gate, facts and scopes, relation kinds, error kinds, exit codes), and `schema.md` generated by `docs/gen_schema_page.py` from `Dossier.model_json_schema()`; nav and Getting Started link them. Observation while writing: only MusicBrainz runs in the identity pass, and `Identity` has no `ambiguities` field; the docs describe the code.

Fix found by the live runs: Wikipedia prose had spaces before punctuation after links and repeated pull quotes wrapped in a `div` (see decisions); `_prose` now joins text nodes as written and skips paragraphs inside a quoted block; `test_sections` (which had asserted `"Lead text ."`) covers both. Re-verified live from the cache on Paranoid Android.

Checks: `uv sync --all-groups --locked`; `uv run poe check` passed (Ruff format and lint, 18 contracts kept, mypy strict on 122 files, 544 tests, 99.23% branch coverage); `uv run --group docs properdocs build --strict` passed with the schema page; `git diff --check` passed; `uv build` produced sdist and wheel; wheel smoke in fresh venvs: base install imports `deadwax` and `deadwax.lookup` without rich or typer, bare `deadwax` exits 1 naming `deadwax[cli]`, with `[cli]` `deadwax --version` prints `deadwax 0.1.0` and `deadwax sources` lists eight sources; `uv run poe audit`: no known vulnerabilities. Not run: pre-commit hooks (they rewrite files), CI (Ubuntu/macOS matrix, lowest-direct job, trivy).

Manual runs on 2026-11-13 (this machine, development proxy, Discogs token and Last.fm key from `.env`, `curl_cffi` installed, Playwright Chromium not installed): `deadwax sources` all ready. Times are wall clock including `uv run`.

| Record | `--no-cache` | cached | Result |
| --- | --- | --- | --- |
| 1 `--track "Radiohead - Paranoid Android"` | exit 0, 15.0 s | exit 0, 9.1 s | identity from seven sources, 1997-05-21 with the Bandcamp 2021 reissue date as a discrepancy, ISRC GBAYE9701376, Discogs master 21491, Wikidata Q1751357; MB credits, weighted tags, Last.fm and Wikipedia texts (lead, writing and recording, composition, release, reception), Odesli links |
| 2 ESTADO DE BIENESTAR, URL and `--album` text | exit 0, 3.4 s (text) | exit 0, 6.9 s (URL) | Bandcamp and Last.fm only; tags, About and Credits texts, 7 Bandcamp recommendations, 10 Last.fm similar artists; every other source `not_found`, Deezer `blocked`; no label (the mobile API has none; the seller "Oráculo Records" is not taken for a label, Stage 5 decision) |
| 3 Huerco S. album | exit 0, 12.3 s | exit 0, 7.7 s | Proibito PRB018 (MB, Discogs) and West Mineral Ltd. (Bandcamp), 2016-06-06 from five sources; `-f json` validated with `Dossier.model_validate_json` (15 tags, 17 texts, 39 relations, 9 links); Odesli `not_found` (no streaming seed) |
| 4 `--track "Кино - Группа крови"` | exit 0, 13.1 s | exit 0, 7.6 s | Cyrillic names kept, five ISRCs, Wikidata Q4150791; iTunes and Odesli `no_match` ("Kino"); Bandcamp 2023 date as a discrepancy. The Japanese fallback was not needed |
| 5 `--track "Everything but the Girl - Missing (Todd Terry Remix)"` | exit 0, 16.5 s | exit 0, 9.8 s | version remix (Todd Terry remix), remixer credit, `remix of` relation; Wikipedia's item (the original song) only in the version discrepancy; artist (iTunes "& Todd Terry") and date (MB 1998 vs 1994) disagreements shown |
| `--timeout 0.01` | exit 3, 0.6 s | — | "Nothing matched", seven `timeout` errors and Odesli `not_found` |

Observations: Deezer answered the Akamai block every time; Discogs review pages were refused by httpx and curl_cffi and then failed for the missing Chromium (`failed`, API facts kept). Cached runs take 7–10 s only because of that review page: errors are not cached, so each run climbs the ladder again (`--exclude discogs` cached: about 1 s). Not changed in this stage.

`uv run poe test-live` (22 library tracks, Discogs token from `.env`): 9 passed, 13 failed, all on the first invariant (no `failed` errors) because of the Discogs reviews error above; the summary lines show `discogs:failed` for exactly those 13. Their later invariants were therefore not checked. Last.fm was `skipped` in every live test: the tests read only the Discogs token from the environment. Three tracks were not found by any source (Ilya Vlasenko "untitled", Jeff Buckley "Sky Blue Skin", the Basinski remix).

Live-verified across stages: MusicBrainz search and lookups, iTunes, Odesli song.link pages, Discogs API with and without token (search with token), Bandcamp pages, search endpoint and mobile API, Last.fm, Wikidata and en/ru Wikipedia, the cache, timeouts, the version gate on a remix, URL resolution (Spotify, Apple Music, Bandcamp, Discogs URLs). Mock-tested only: Deezer success paths (blocked from this network), Discogs review parsing and the browser step of the ladder (Chromium not installed), Bandcamp HTML search and the blocked-page mobile fallback, Last.fm error codes other than 6, Wikidata P444 scores, ja/de/fr section lists, retry on `Retry-After` dates, rate-limited errors.

Open items for the user: install Chromium (`uv run playwright install chromium`) or treat a missing escalation browser as `skipped` so the live invariant holds; pass the Last.fm key to the live tests; consider caching refused review pages for a short time. All three were closed in the Stage 7 follow-up below. No commit was created.

### 2026-11-13 — Stage 6 qualification

Fixtures recorded on 2026-11-13 (`scripts/record_fixtures.py --live lastfm,wikipedia,odesli`, the Last.fm key from `.env`; other sources replayed): all nine scenarios for Wikipedia and Last.fm, four for Odesli (the others have no streaming seed); 3.3 MB. The first user run produced Odesli fixtures of 308 redirects only and no Last.fm fixtures: the raw seed URL (`song.link/https://…`) is normalized by a 308, the recorder crashed on the redirected request (`RequestNotRead`: a redirected request arrives with an unread stream), an Apple seed lost its `?i=` track parameter, and the key line in `.env` was still commented. Fixed: the seed is URL-encoded (one 302 to `/s/<id>` or `/i/<id>`), the recorder reads the request before keying it, fixtures store `location` for redirects and both replays send it. The remaining five scenarios were recorded by the agent with the key from `.env` (exit 0, no traceback; the key does not appear in fixtures).

Live-verified through the recorded runs: Paranoid Android gets Wikidata label, lyricist, producer, `appears_on` OK Computer, the en lead and four sections, Last.fm weighted tags and 20 similar tracks, and Odesli links (Pandora, Tidal, Yandex, Anghami…); Кино gets the ru article (lead, «Смысл», «История песни»), lyricist «Виктор Цой», similar Russian rock tracks, while Odesli reports `no_match` (Spotify spells the band "Kino"); Huerco S. gets seven scores from the ratings template (Metacritic 85/100, Pitchfork 8.1/10…) and the identity through the alias; the Todd Terry remix keeps Wikidata's original song out (`other_version`) and gets Last.fm tags and similar tracks of the remix itself; the unknown query gets `not_found` from Last.fm and Wikipedia. Mock-tested only: Last.fm error codes 29 and others, Wikidata P444 scores (none of the check items has one), ja/de/fr section lists, CirrusSearch with a non-Latin title through the adapter (verified by hand: OK Computer and «Группа крови» found).

Checks: `uv run poe check` passed (Ruff format and lint, 18 contracts kept, mypy strict on 121 files, 544 tests, 99.22% branch coverage); `uv run --group docs properdocs build --strict` passed. Not run: pre-commit hooks, `poe audit`, `poe test-live`, CI. No commit was created.

### 2026-11-13 — Stage 6 interim (awaiting fixtures)

Live Wikimedia probes (honest User-Agent, plain httpx): Wikidata items Q1751357 (Paranoid Android, a single), Q202996 (OK Computer), Q4150791 and Q2725250 (Кино's song and album), Q104869719 (Huerco S.), Q3859219 (Missing); en articles use `{{Album ratings}}` (up to three per article; `revNscore` and `revNScore` both occur), ru album articles `{{Рейтинги альбома}}`; level-2 headings are `div.mw-heading2 > h2`. Radiohead's item has only a `mul` label; Huerco S.'s performer item is labelled "Pendant" with the alias "Huerco S."; a song's P436/P1954 name its single, not the album; the en sitelink of «Группа крови (песня)» redirects to the album article. The Wikipedia adapter ran live on all five check records before fixtures existed.

Implemented: `sources/lastfm` and `sources/wikipedia` packages, wired into `lookup`, R4 and two R8 contracts (18 kept); score-only texts deduplicated by publication, rating, and title and rendered as one line; recorder hosts and `DEADWAX_LASTFM__API_KEY`; docs. Unit tests on hand-written responses pass; the 10 replay tests in `tests/sources/test_lookup.py` fail until the new fixtures are recorded.

### 2026-11-12 — Stage 5 qualification

Live probes before coding (this machine, through the local proxy): Bandcamp album and track pages, the `bcsearch_public_api` autocomplete endpoint (POST JSON), and the mobile `api/mobile/24/tralbum_details` answered plain httpx; the HTML `/search` page answered a Fastly "Client Challenge" with status 200. Discogs API and pages answered a branded 403 to every User-Agent containing "deadwax" and 200 to library User-Agents (see decisions); with `python-httpx` the API shapes of master, release, versions, artist, and label releases were confirmed. The Discogs release page and Bandcamp HTML search could not be inspected: the auto-mode classifier refused fetching them with browser headers, and no workaround was tried.

Added `sources/_html.py` (lexbor parser, text, attributes, JSON in attributes, JSON-LD by type), the `bandcamp` package (`models`, `parse`: page record from data attributes and JSON-LD, fan comments, recommendations, "X by Y" credit lines, mobile details, compilation rule, search results, HTML search, label grid; `adapter`: query URL, MusicBrainz links of the right kind first, search; album↔track page moves; mobile API for the label and as blocked-page fallback; label page), and the `discogs` package (`models`, `parse`: names without disambiguation, roles with details, track ranges, release and track credits, notes as wiki texts, labels without placeholders, barcodes, versions, members/groups/aliases, label releases, compilations, search results, JSON-LD reviews; `adapter`: query IDs, earlier-pass IDs, token search; master → main release; versions, artist, label catalog, compilations with token, reviews through a second browser-profile client). `SourceSettings.user_agent` for every source; `HttpAdapter.client_spec()`; Discogs status detail and the CLI sources table hint. Contracts: R4 now `lookup` → `musicbrainz | itunes | deezer | odesli | discogs | bandcamp` → `_base | _html` → `_http` → `config`; new "R8: Bandcamp adapter modules" and "R8: Discogs adapter modules" (16 contracts). `scripts/record_fixtures.py` gained the hybrid mode, `--live`, body-hash keys, the Discogs token from `DEADWAX_DISCOGS__TOKEN`, and scenarios `bandcamp_url`, `discogs_url`. `tests/integration/test_library.py` holds 22 tracks from the user's library (tags read from the files; "Various Artists" tracks use the artist from the title; one untagged file its name).

Fixtures recorded by the user on 2026-11-12 (`uv run python scripts/record_fixtures.py`, no Discogs token, `escalation=none`): Bandcamp and Discogs for all nine scenarios (3.6 MB of new fixture files), all sources for `bandcamp_url` and `discogs_url` (MusicBrainz answered three 503s, recovered). Live-verified through that run: Discogs API by IDs from MusicBrainz for Paranoid Android (master 21491), Huerco S. (1016511), Кино (90716, a "Not On Label" self-release), and the OK Computer URL; the Discogs release page answered 403 every time (reported `blocked`, API facts kept); Bandcamp found Paranoid Android and OK Computer on `radiohead.bandcamp.com` and Кино on `kinogroup.bandcamp.com` through the search endpoint, read Huerco S. from the MusicBrainz link and from the URL query (resolver first), labelled it "West Mineral Ltd." from the mobile API, and found the Todd Terry remix only on a third-party compilation (now reduced by the compilation rule); the remix and the unknown query have no Discogs ID and report `skipped`. Afterwards one recorded entry each was removed: Bandcamp HTML search in `no_match` and the "Not On Label" catalog in `kino`, which the fixed code no longer requests.

Mock-tested only: Discogs search and compilations (no token), reviews parsing (hand-written JSON-LD), the escalation path of the review page, Bandcamp HTML search markup, the label `/music` page as a lookup step (parsed from a real artist page), and the blocked-page mobile fallback. Not run: `deadwax` CLI live runs with escalation, `poe test-live`, pre-commit hooks, `poe audit`, CI.

Checks: `uv run poe check` passed (Ruff format and lint, 16 contracts kept, mypy strict, 478 tests, 99.25% branch coverage); `uv run --group docs properdocs build --strict` passed. No commit was created.

### 2026-11-12 — Stage 4 qualification

CLI: `cli/app.py` (group that defaults to `lookup`; `lookup` with `--album/--track` (both → exit 2), `--sources`, `--exclude`, `--format/-f pretty|json|markdown`, `--no-cache`, `--timeout`, `--config`, `--verbose/-V`; `sources` with `--format`, `--config`, `--verbose`; exit codes 0 found, 1 unexpected, 2 usage or configuration including `InvalidQueryError` and unknown source names, 3 nothing matched), `cli/settings.py` (every `SourcesConfig` section plus `log`, `adapter_timeout`, `config_file`; TOML source; `sources_config()` puts the cache at `responses.sqlite` in the platformdirs user cache dir), `cli/render.py` (rich sections Identity with highlighted disagreements, Tags, Credits, Texts truncated at 600 characters, Relations grouped by kind, Links, Errors; every fact names its sources once, linked to the first page; sources table shows `missing DEADWAX_ODESLI__API_KEY`). `main.py` also reports a missing extra for rich and platformdirs. `.env.example` lists all 48 settings; the configuration page explains the precedence and shows short type names. README and Getting Started describe the command and the library call.

First live manual runs on 2026-11-12 (this machine, through the development proxy): `deadwax sources` (MusicBrainz, iTunes, Deezer ready; Odesli `missing DEADWAX_ODESLI__API_KEY`); `deadwax --track "Radiohead - Paranoid Android" --no-cache` exit 0 in 9.1 s with the 1997 original recording, two MusicBrainz 503 retries visible in the log, Deezer `blocked`; the same without `--no-cache` from the cache in 1.2 s; `--timeout 0.01` printed "Nothing matched the query" with three `timeout` errors and exit 3; the Spotify URL gave the same recording (exit 0); the Huerco S. album with `-f json` validated as `Dossier` (Proibito, 5 links); the Todd Terry remix with `-f markdown` showed version remix, `remix_of` Missing and the artist/date disagreements; `--sources spotify` exited 2 naming the known sources.

Checks: `uv run poe check` passed (Ruff format and lint, 14 contracts kept, mypy strict on 88 files, 407 tests, 99.03% branch coverage); `uv run --group docs properdocs build --strict` passed; `uv build` produced sdist and wheel; wheel smoke: base install imports and `deadwax.lookup` loads without rich, bare `deadwax` exits 1 naming `deadwax[cli]`, with the `cli` extra `deadwax --version` prints `deadwax 0.1.0` and `deadwax sources` prints the table. Not run: pre-commit hooks, `poe audit`, CI. No commit was created.

### 2026-11-12 — Stage 3 qualification

Live checks before coding: MusicBrainz WS/2 answered; `api.song.link` answered `401 PUBLIC_API_ACCESS_DEPRECATED` for every request (retired 2026-07-31); `api.deezer.com` answered an Akamai "Access Denied" 403 from this network (not retried with other headers); iTunes Search answered. The user chose keyless sources with Odesli behind a key.

Added `sources/_base.py` (`HttpAdapter` with lazy client and status from settings, `service_for_url`, `link_target`, `search_key`), the `musicbrainz` package (`models`, `parse`, `adapter`: lookup by MusicBrainz IDs, by any URL through `ws/2/url`, by ISRC from earlier passes, or by search; recording, first release, its release group, work and artist; release group, first release with track-level credits, and artist for albums), `itunes`, `deezer` (errors inside HTTP 200 bodies mapped to not found / rate limited / failed), `odesli` (key only, `key` stripped from cache keys and URLs), `lookup` (`lookup`, `build_adapters`, `describe_sources`; resolver order MusicBrainz, Odesli, iTunes, Deezer). Config gained `itunes`, `deezer`, `odesli.api_key`, `http.retry_base`; challenge detection recognises Akamai block pages (also entity-encoded). Core: `SourceInfo`; Apple Music URLs without a title slug are recognised. `deadwax` exports `lookup`, `describe_sources`, the settings classes, `SourceInfo`, `SourceStatus`, `SourceState`, `Pass`, `Capability`, `Requirement`, loading `deadwax.sources` lazily. Contracts: R4 now `lookup` → adapters → `_base` → `_http` → `config`; new "R8: MusicBrainz adapter modules".

Fixtures: `scripts/record_fixtures.py` ran the real `lookup()` through a recording transport (uncompressed, last response per request, secret parameters dropped) on 2026-11-12 for seven scenarios: `paranoid_android`, `huerco_s`, `kino`, `missing_remix`, `spotify_url`, `apple_url`, `no_match` (2.3 MB in `tests/fixtures/{musicbrainz,itunes,deezer}/`). Deezer fixtures contain only the 403 block pages; Deezer and Odesli parsers are tested with hand-written responses in their documented shape, so their success paths are not live-verified.

Live-verified on 2026-11-12 (recording runs, reviewed as Markdown): Paranoid Android resolves to the 1997 original recording (`9f9cf187…`) with ISRCs, 35 credits, writers from the work, members, covers, a mash-up, Discogs master 21491, Wikidata Q1751357, Spotify/Deezer/Apple/Tidal links; the Spotify and Apple URLs reach the same recording; the Huerco S. album has Proibito PRB018, producer Brian Leeds per track, Bandcamp/Boomkat/Amazon links; Кино keeps Cyrillic names, iTunes reports `no_match` for "Kino"; the Todd Terry remix stays separate from the 1994 original (`remix_of` the work "Missing", remixer Todd Terry, artist and date disagreements with iTunes shown); the unknown query yields no identity and `not_found` errors. Recording runs hit MusicBrainz 503 "server busy" on many requests; retries recovered except twice, which were re-recorded after raising the retry base.

Checks: `uv run poe check` passed (Ruff format and lint, 14 contracts kept, mypy strict on 85 files including `scripts/`, 378 tests, 99.08% branch coverage); `uv run --group docs properdocs build --strict` passed. No commit was created.

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
