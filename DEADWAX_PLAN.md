# deadwax v2: implementation plan and handoff journal

## Status and handoff

This is the active specification and multi-session handoff for deadwax. deadwax collects, for one track or album, what open sources know about that exact recording, with four goals: (1) texts describing its sound, (2) relations for further searches, (3) confirmation of the exact recording and version with visible discrepancies, (4) streaming links. v1 (eight sources) is complete; its plan, stage evidence, and full decision log are archived in [`plans/v1.md`](plans/v1.md). Closed v2 stages (8–17, 19, R-1–R-5), their evidence, and the v2 decision log are archived in [`plans/v2.md`](plans/v2.md).

- **Status:** v1 complete and committed. v2 source scope recorded (`## v2 sources`); v2 stages 8–20 defined; Stages 8–17 and 19 done, Stage 18 deferred until RYM is accessible (Boomkat and Norman Records remain access-limited). Structural refactoring stages R-1–R-6 (2026-11-19) run before Stage 20; R-1–R-6 done; Stage 20 is next.
- **Branch:** `main`. Agents never create commits on the user's behalf.
- **Working rule:** complete one stage, run its acceptance checks, append dated evidence, update the status table, report an English Conventional Commit suggestion, and stop. Resume the next stage only when the user asks.
- Read `AGENTS.md` and `docs/architecture.md` (import rules R1–R9) before code changes. After code changes run `uv run poe check`; after docs or public docstring changes also run `uv run --group docs properdocs build --strict`.
- Before changing a v1 adapter, read its rows in the decision log of `plans/v1.md`; before changing a v2 adapter, its stage and evidence in `plans/v2.md`.

### Accepted decisions

| Topic | Decision |
| --- | --- |
| Names | Distribution `deadwax`, package `deadwax`, command `deadwax`, env prefix `DEADWAX_`, error base `DeadwaxError`. |
| Entity kind | Text queries **must** state `--album` or `--track`. A URL implies its kind; a flag that contradicts the URL is a usage error. A URL whose kind only a request reveals leaves `Query.kind` unset for the resolver adapter. |
| Anti-bot | HTML sources: browser header profiles, HTTP/2, cookies, jitter, Retry-After, challenge detection, and the escalation ladder httpx → curl_cffi (`stealth`) → Playwright (`browser`). Official APIs: an honest `deadwax/<ver> (+contact)` User-Agent unless the source's `user_agent` setting says otherwise. |
| Streaming links | MusicBrainz URL relations, iTunes Search, and Deezer in the first two passes; Odesli reads the song.link page in the links pass. |
| Language | Code, docs, plan journal, commit messages in English. |
| Git | No agent commits; stop after each stage with a Conventional Commit suggestion (AGENTS.md "Commit Handoff"). |

### Product contract

deadwax is general-purpose: output is equally useful to a person in a terminal (`--format pretty|markdown`) and to a program reading JSON. Every fact carries `source` (adapter) and `url`. Nothing is invented or "completed": no data means an empty field. A candidate with a different version is never merged into the main record; it goes to relations or is dropped, and the disagreement is recorded in identity. A failing adapter never breaks the others; it appears in `errors`.

Never used: Juno Download (shut down), Every Noise at Once, direct Metacritic scraping (ratings come from Wikipedia), Spotify audio features.

## v1 baseline

- Sources: MusicBrainz, iTunes, Deezer (identity pass); Discogs, Bandcamp, Last.fm, Wikipedia/Wikidata (enrichment pass); Odesli (links pass).
- Layers, import rules R1–R9 and contracts: `docs/architecture.md`, `pyproject.toml`. Sources, lookup flow, escalation and cache: `docs/sources.md`. Dossier model: `docs/output.md` and `src/deadwax/core/models.py`. Original design notes (package layout, data model, per-adapter coverage, HTTP stack, CLI): `plans/v1.md`.
- Tests: network off (pytest-socket); adapters get an injected client and replay recorded fixtures from `tests/fixtures/<source>/` (`scripts/record_fixtures.py`); opt-in live invariants in `tests/integration` (`poe test-live`); 95% branch coverage.

### Standing decisions

Carried from the v1 decision log, where each has its date and reason. They apply to v2 sources unless a new decision supersedes one.

- Fact URLs are plain strings, not `HttpUrl`.
- Relation kinds are directional (`cover_of`/`covered_by`, `remix_of`/`remixed_by`, `samples`/`sampled_by`).
- A candidate with a different version: its facts are dropped, it becomes an `other_version` relation, and the disagreement is a `version` discrepancy. An unrelated candidate is a `no_match` error. For a URL query the resolver runs first and its candidate is the reference.
- Every adapter, store adapters included, contributes facts through the same matching gate.
- Passes: identity → enrichment → links. Each pass's context is the identity and links of a merge of the earlier passes, so rejected candidates leak no IDs.
- `SourceError` (`BlockedError`, `RateLimitedError`, `NotFoundError`) lives in `core.errors`; the orchestrator maps it to `ErrorKind`.
- Adapters are constructed with their settings; `status()` takes no arguments; `requires` lists setting paths (`sources.discogs.token`) that the CLI maps to `DEADWAX_` names.
- Excluded and disabled adapters produce no error; a missing key or extra gives `skipped`; unknown names in include/exclude raise `ConfigurationError`.
- Every source has `user_agent` and `proxy` settings (`direct` bypasses the environment proxy). The CLI exposes every `LookupConfig` section (per-source settings under `sources`, since R-4); each field is described and listed in `.env.example`.
- Default API contact is the repository URL.
- Shared adapter code lives in `sources/_search.py`, `_adapter.py`, `services.py`, `_html`, `_http`; adapters never import each other. Every adapter is a package `sources/adapters/<name>/` (since R-1).
- `deadwax` imports `deadwax.sources` lazily.
- Trace event names are members of `TraceEvent` (`core/events.py`); `trace()` and `RunJournal.event()` accept only them, and `docs/runs.md` lists them (since R-6).
- Captcha widget markers count as a challenge only on 403/429/503; interstitial markers on any status.
- With `http.escalation` unset, a step that cannot run ends the ladder: the page is `blocked`. An explicitly chosen step that cannot run is a `ConfigurationError`.
- Responses are cached per adapter TTL, a 404 for a day, a blocked page for `cache.blocked_ttl`; other errors are never cached.
- Scores without review text are `Text(kind=review, body="")` with publication and rating.
- Non-Latin names are compared as written; alias-aware matching is a later, separate change.
- Fixtures: sources not being recorded are replayed; requests with a body are keyed with a body hash; recording and source tests run with `escalation=none`; credentials go only to sources recorded live.
- Generated docs pages (configuration, output schema, API reference) are never edited by hand; README holds the source tier tables.

## v2 sources

Scope agreed with the user on 2026-11-13 after reviewing what each planned source can give. Each source is one adapter (the press sites share one adapter with per-site rules) and follows the product contract and the standing decisions. Access notes are unverified and are checked at each source's stage.

| Group | Source | Extracts (v1 model terms) | Access |
| --- | --- | --- | --- |
| Shops | Boomkat | editorial descriptions → `shop` texts; genre sections | HTML, Cloudflare |
| Shops | Juno | `shop` texts; genres; "also bought" → `similar` | HTML |
| Shops | Norman Records | staff reviews → `shop` texts; tags | HTML |
| Shops | Forced Exposure | label press texts → `label`/`shop` texts | HTML |
| Shops | Hard Wax | one-line `shop` texts; genre sections | HTML |
| Shops | Phonica (implemented, opt-in) | staff `shop` texts; genres | HTML, Sucuri; search API uses a browser session |
| Shops | Soundohm | `shop` texts (often label press copy) | HTML |
| Shops | Bleep | `shop` texts; genres; related releases → `similar` | HTML |
| Press | AllMusic | review with rating and critic; moods and themes → `mood`/`theme` tags; styles; credits; similar albums | HTML, anti-bot |
| Press | Resident Advisor | reviews; artist and label bios; DJ charts containing the track → relations | unofficial GraphQL |
| Press | Press adapter (Pitchfork, The Quietus, The Wire…) | review excerpt, score, link | HTML, per-site rules |
| Catalogues | Rate Your Music | primary and secondary genres; descriptors → `descriptor` tags; rating with vote count; chart positions; user reviews | browser only; ToS forbids scraping |
| Catalogues | Genius | song description and annotations → texts; credits; samples, interpolations, covers, remixes → relations; lyrics | API with token; lyrics only in HTML |
| Catalogues | Album of the Year | critic scores per publication with review links; user score; genres | HTML, Cloudflare |
| Catalogues | ListenBrainz | similar recordings and artists; listen counts; CritiqueBrainz reviews (CC) | open API by MBID |
| Catalogues | SecondHandSongs | original and first release; writers; covers and adaptations with dates → relations | API |
| Radio and mixes | NTS | episodes that played the track → `broadcast`; neighbouring tracks; episode genres | unofficial JSON |
| Radio and mixes | 1001Tracklists | sets → `mix`; supporting DJs; neighbours in sets | HTML, anti-bot; ToS |
| Radio and mixes | KEXP | plays with dates → `broadcast`; DJ comments → texts | open API |
| Radio and mixes | WFMU | playlists → `broadcast`; DJ comments → texts | HTML |
| Streaming | Spotify | links; popularity; label; copyrights; ISRC (no audio features) | Web API, client credentials |
| Streaming | SoundCloud | uploader descriptions; tags; counts; reposters → relations; uploads absent elsewhere (edits, bootlegs) | no new API apps; web client |
| Streaming | YouTube | links only | Data API key |
| Streaming | Beatport | BPM; key; subgenre; mix name (version identity); ISRC; remixers; DJ charts → relations | `__NEXT_DATA__` JSON |
| Streaming | Juno Download (dropped: shut down) | BPM; genre; label | HTML |
| Samples | WhoSampled | samples used and sampled by, with timestamp and element; covers; remixes → relations | no API; ToS forbids scraping |

Not planned: Rough Trade, Apple Music, Traxsource, Mixcloud, BBC Sounds.

Open questions, settled at each source's stage:

- Access to sources whose terms forbid scraping (Rate Your Music, 1001Tracklists, WhoSampled).
- Whether lyrics (Genius) are stored, and how much of a press review is kept.
- Model additions: BPM and key, lyrics, tags of an episode or set marked as context rather than the track's own, deduplication of shop texts that repeat one label press release. The v1 model already has `shop` texts, `mood`/`theme`/`descriptor` tags, and `mix`/`broadcast`/`samples`/`sampled_by` relations.

## Implementation stages and acceptance criteria

Numbering continues after v1 (stages 0–7 in `plans/v1.md`). Sections of closed stages are in `plans/v2.md`. Order: shared infrastructure first; clean APIs next, to prove it; each model addition lands in the first stage whose source needs it; sources behind bot protection or with open terms-of-service questions last, so those decisions can be made meanwhile.

| Stage | Status | Deliverable |
| --- | --- | --- |
| 8 | Done | Foundation: source groups, default source set, per-lookup concurrency cap, shared search → page helper. |
| 9 | Done | ListenBrainz, SecondHandSongs, KEXP. |
| 10 | Done | Spotify, YouTube (links only), SoundCloud. |
| 11 | Done (Beatport not live-verified) | Beatport (Juno Download dropped: shut down); BPM and key. |
| 12 | Done (Juno live-verified once by the agent) | Shops I: Juno, Hard Wax, Soundohm; shop-text deduplication (Phonica moved to the unscheduled blocking item). |
| 13 | Done | Shops II: Forced Exposure and Bleep; Nodriver repair. Boomkat and Norman Records deferred after retry. |
| 14 | Done | Genius. |
| 15 | Done | Reviews I: AllMusic, Album of the Year. |
| 16 | Done | Reviews II: press adapter with per-site rules, Resident Advisor; RA DJ charts dropped after site redesign. |
| 17 | Done | Radio: NTS, WFMU; context tags. |
| 18 | Deferred (RYM access blocked) | Provisional Rate Your Music adapter and browser-first fetching; parser and live results unverified. |
| 19 | Done (WhoSampled access intermittent) | 1001Tracklists, WhoSampled. |
| R-1 | Done | Layout: adapters in `sources/adapters/`, one package per adapter, tests per source, `_base` split, source `ra`, fixtures `tracklists`. |
| R-2 | Done | Shared helpers: `prose()`, JSON through models, adapter access description. |
| R-3 | Done | Service catalogue in `sources/services.py`; `service` and default `resolves()` on every adapter; URL rules leave the core. |
| R-4 | Done | Source defaults in settings, `LookupConfig` with a `sources` section shared by the CLI, resolved settings for `HttpClient`, registry. |
| R-5 | Done | Core: `Facts` base, `deadline` module, access label out of the core, nested `SourceInfo.access`, shared formatters. |
| R-6 | Done | Trace event names, repository cleanup, journal split, architecture docs. |
| 20 | Not started | Qualification. |

Common acceptance for source stages 9–19, in addition to each stage's own:

- The adapter declares its `group`. An open-API source of the agreed default set (ListenBrainz, SecondHandSongs, KEXP, Spotify, YouTube, Genius) is added to `DEFAULT_SOURCES` in `sources/config.py` in its stage; other sources stay opt-in.
- An HTML source that searches and reads one page builds on `SearchPageAdapter` in `sources/_search.py` (formerly `_base.py`), or the evidence says why not.

- Fixture tests for every extraction path, and for not found, blocked, and a missing key where one applies.
- The matching gate drops a candidate of another version (tested).
- Every new setting has a description and a line in `.env.example`; the source is described in `docs/sources.md` and the README tables.
- `uv run poe check` and the strict docs build pass.
- Live runs on the five v1 check records and at least one record the source is strong on; the report separates mock-tested from live-verified behaviour.

### Stage 18: Rate Your Music

- [x] The user confirmed express permission for automated RYM access.
- [x] Browser-first fetching for a source that never answers plain httpx.
- [ ] Verify primary and secondary genres, descriptor tags, rating with vote count, chart positions, and user reviews against real RYM pages. The provisional parser is covered only by synthetic HTML and remains opt-in.

**Deferred until:** RYM search and record pages can be captured and live lookups run. Do not mark this stage done from synthetic fixtures. Stage 19 may proceed independently when requested.

**Suggested message:** `feat(sources): add Rate Your Music adapter`.

### Structural refactoring R-1–R-6

Agreed with the user on 2026-11-19 after a structure review. Goal: one source of truth per source, less duplication, cleaner layer boundaries. Breaking changes to the public API and `DEADWAX_*` names are allowed (0.1.0, never released); such commits carry `!`. Each stage passes `uv run poe check` and the strict docs build, changes no lookup behaviour unless stated, and ends with evidence and a commit suggestion.

- **R-1 (layout, no logic changes).** All adapters move to `deadwax.sources.adapters`; each is a package with `adapter`, `parse`, and optionally `models`. `_base.py` splits into `_adapter.py` (`HttpAdapter`) and `_search.py` (search helpers, `SearchPageAdapter`, `track_on_release`). The package of adapter `pressreviews` is named `pressreviews` (the source keeps its name: `press` is a group name); source `residentadvisor` is renamed `ra` (`DEADWAX_RA__*`); fixtures `1001tracklists` move to `tracklists`. Tests mirror the packages in `tests/sources/adapters/<name>/`; stage-named test files are split per source. import-linter: one independence contract over the adapters and one layers contract with containers for their modules replace the per-adapter R8 contracts.
- **R-2 (shared helpers).** `prose()` in `_html`; JSON of NTS, Resident Advisor, and Genius read through Pydantic models; `HttpAdapter.access()` replaces `lookup._access`.
- **R-3 (service catalogue).** `sources/services.py` holds each service's hosts and URL rules, replacing `_SERVICES` and the core's `_URL_RULES`; the core keeps a generic `recognize_url(url, rules)`; URL query parsing moves to sources while `deadwax.parse_query` stays public. Every adapter declares `service`; the default `resolves()` uses it.
- **R-4 (configuration).** Per-source rate, HTML transports, and browser mode become defaults of that source's settings; `SourcesConfig` becomes `LookupConfig` with a typed `sources` section (`DEADWAX_SOURCES__<NAME>__*`) that the CLI reuses instead of repeating fields; `HttpClient` receives resolved settings of its source; the adapter list moves to `sources/registry.py` with a test that it matches the settings; `Escalation.PATCHRIGHT` is normalized in one validator. Per-source settings classes leave `deadwax.__all__`.
- **R-5 (core).** `Facts` base shared by `Partial` and `Dossier`; adapter time budget in `core/deadline.py`; `SourceAccess.label` moves to CLI rendering; `SourceInfo.access` nested; shared text formatters for Markdown and rich output.
- **R-6 (cleanup).** Trace event names as an enum used by sources and the run renderer; decide on `plans/phonica-search.patch` (referenced above); closed v2 stages archived to `plans/v2.md`; `docs/architecture.md` rewritten for the registry and adapter packages.

### Stage 20: qualification

- [ ] README source tiers and docs pages for every v2 source.
- [ ] Full checks, package build and wheel smoke, audit; `poe test-live` with the v2 sources.
- [ ] Manual runs on the check records with the default set and with every source; the time of a full lookup recorded.

**Acceptance:** all checks pass or blocked ones have precise reasons. **Suggested message:** `docs: document sources and qualify deadwax v2`.

### Later, unscheduled: automation masking for Cloudflare-protected sources

- [ ] Masking browser automation (stealth plugins, undetected-chromedriver, nodriver, Camoufox, fingerprint spoofing) so that Beatport and similar sources pass Cloudflare challenges that defeat httpx, curl_cffi, and plain Playwright.
- [x] Phonica (moved from Stage 12 on 2026-11-13 at the user's request): restored after a dedicated Patchright profile opened its product pages and search API in headed and headless modes. The restored adapter includes the JSON search once kept in `plans/phonica-search.patch` (removed in R-6); the earlier adapter remains in commit `9af10f2`.

Recorded at the user's request on 2026-11-13. Pros: no manual step per lookup. Cons: an arms race with Cloudflare's detection, breaks with its updates, heavy and fragile code, against Beatport's terms and its explicit refusal of automated clients. Coding agents do not implement this item: Claude Code declines it, and its safety classifier refused even running the existing ladder against Beatport. It is not part of any stage and is not taken as the next action.

## Verification

- `uv sync --all-groups --locked`, `uv run poe check`, `uv run --group docs properdocs build --strict`, `uv build` with wheel smoke, `uv run poe audit`.
- Manual: `deadwax sources`; the five v1 check records (`plans/v1.md`, "Five manual-check records") plus records chosen for each new source, in `--format pretty`, first with `--no-cache`; `poe test-live`. Reports separate mock-tested from live-verified behaviour.

## Risks

| Risk | Handling |
| --- | --- |
| Scraped markup and undocumented endpoints change | Several extraction paths per page where possible; parse failures → `AdapterError`; fixtures re-recordable. |
| Bot protection on HTML sources | Escalation ladder; otherwise an explicit `blocked` error, never partial guesses. |
| Terms of service forbid automated access (Rate Your Music, 1001Tracklists, WhoSampled) | Decided per source with the user before its stage starts. |
| Ambiguous identity in noisy data (tracklists, shop listings) | Matching gate, `ambiguities` and `discrepancies`; never merge on title alone. |
| Rate limits | Per-host limiter and cache; rate-limited → `AdapterError(rate_limited)`. |

## Progress evidence and decision log

Update the stage table only after its acceptance gate passes. Append dated evidence under the newest entry: what changed, exact commands and outcomes, what remains. Do not replace old evidence. Keep decisions distinct from observations.

### 2026-11-19 — R-6 evidence (cleanup)

Changed:
- `core/events.py`: public `TraceEvent` (`StrEnum`, 24 members, values unchanged: `run.start` … `wfmu.truncated`), exported from `deadwax.core` and `deadwax`. `trace()` and `RunJournal.event()` take a `TraceEvent` and log its plain string, so `record.msg` and the journal stay `str`. Core, sources (HTTP client, search helper, MusicBrainz, YouTube, AllMusic, Beatport, WFMU), `logs/runs.py`, `cli/app.py`, and the run renderer use members instead of literals; the renderer's synthetic `reference` line is a local constant.
- `plans/phonica-search.patch` removed: its adapter, models, parser, fixtures, and tests are in the tree since the 2026-11-14 restore. The untracked leftover `src/deadwax/sources/junodownload/` (bytecode only) removed.
- Journal split: Stages 8–17 and 19, their evidence, the v2 decision log, and the R-1–R-5 evidence moved verbatim to `plans/v2.md` (headings added for the decision log and the Stage 8 evidence; the empty "Resume instructions" heading dropped). Stage 18, the "Stage 20 partial" entries, and the Deezer entry stay here. AGENTS.md and the status section point to `plans/v2.md`; a standing decision names `TraceEvent`.
- `docs/architecture.md`: layer table updated for the service catalogue and per-source settings; new "Lookup flow" and "Adding a source" sections; R5 names `TraceEvent`. Contract "R8: HTTP stack modules" renamed "R4: HTTP stack modules" (rule text unchanged). `docs/runs.md` lists every event name.
- Tests use `TraceEvent` members; new tests check that names are dotted lowercase and that records carry plain strings.

Decisions:
- (agent) `trace()` accepts only `TraceEvent` members (breaking for callers that passed their own names).
- (agent) The patch is deleted rather than archived: everything in it is in the tree, and commit `9af10f2` keeps the earlier adapter.

Checks: `uv run poe check` passed (fmt-check, lint, lint-imports 16 contracts kept, mypy, 1057 tests, coverage 96.89%); `uv run --group docs properdocs build --strict` passed; no string event literals left in `src` or `tests`; `deadwax runs` renders a journal recorded before the change. No live runs (refactor only).

**Suggested message:** `refactor!: name trace events with an enum, archive closed v2 stages, and rewrite the architecture docs`.

### 2026-11-19 — Alternative titles, refusals without fallback, WFMU deadline (Stage 20 partial)

Run `20261119T125334Z-f0e2c9` (`radiohead - there there`) after `7a5ede9`: Beatport succeeded. Remaining causes from its journal and decisions (user):
- Alternative title in brackets. The Hail to the Thief recording `04207ca7` and SecondHandSongs performance 277084 are titled `There There. (The Boney King of Nowhere.)`; `title_similarity` was 0.458, so MusicBrainz chose the compilation-only recording `bb4dcf01`, which led AllMusic to the compilation page and KEXP to the wrong recording. `title_similarity` now also compares titles without a trailing bracket of at least three words that names no distinguishing word (part, number, Roman numeral, reprise, interlude, intro, outro, prelude, version, mix, take, session, recording, demo, …). The three-word minimum came from a regression in the Juno fixture: `Missing (Tee Beat)` is an unmarked mix name, and it still does not match `Missing`.
- Deezer's Akamai block opened a headed fallback (26 s) with the same result. The fallback now applies only to `SOLVABLE_CHALLENGES`. The block itself depends on the route (`DEADWAX_DEEZER__PROXY=direct`).
- WFMU read playlists one after another until the 30 s timeout and lost what it had found. The core exports `adapter_time_left()`; WFMU stops before another playlist when fewer than 5 s remain and one playlist with the track has been read, tracing `wfmu.truncated`.
- Album of the Year: a track query rejected the single *There, There* on kind. For a track query the adapter now searches releases and accepts a release page only when its tracklist (`#tracklist .trackList li`) lists the track; it returns a TRACK candidate with an `appears_on` relation through `track_on_release`, and release facts keep their release-group scope. The fixture `there_there_single.html` was saved by Claude through the Patchright transport with the user's persistent profile (no challenge appeared).
- Not changed: Forced Exposure HTTP 403, RYM Cloudflare 403, Boomkat (album search for tracks not chosen).

Verification: `uv run poe check` passed (995 offline tests, 96.77% coverage); `uv run --group docs properdocs build --strict` passed. Live behaviour unverified.

### 2026-11-19 — Loaded documents, refusals, and the There There identity (Stage 20 partial)

Run `20261119T124341Z-631257` (`radiohead - there there`, 103 s) after `75beef9`: Discogs and Genius succeeded through the headed browser; WhoSampled reported `not_found`; RYM `blocked` (Cloudflare HTTP 503). Remaining:
- Beatport: the track page loaded after a manual challenge (200, 220 KB) but its `__NEXT_DATA__` was not valid JSON, while the same page parsed in the previous run. Likely the content was read while the reloaded document was still loading.
- Deezer: the headed fallback showed an Akamai block, a refusal of the address with nothing to solve, yet waited 60 s with the prompt.
- AllMusic: the page was the *Mercury Music Prize 2003* compilation. MusicBrainz chose recording `bb4dcf01`, which appears only on two compilations, because the Hail to the Thief recording `04207ca7` (50 releases) is titled `There There. (The Boney King of Nowhere.)` and `compare` gives `title_score=0.46` → `no_match`. The parenthetical alternative title is not a version marker and stays in the base title. Not fixed: changing core matching needs a decision.

Changed: Patchright and Nodriver treat a page as ready only when `document.readyState` is not `loading` (transient navigation errors during that check are retried). The prompt and the manual wait apply only to `SOLVABLE_CHALLENGES` (Cloudflare challenge or Turnstile, captchas, AWS WAF, Fastly, Sucuri); refusals return at once. Beatport records `parse.unrecognized` (length, head, tail of the state) before its JSON error.

Verification: `uv run poe check` passed (978 offline tests, 96.75% coverage); `uv run --group docs properdocs build --strict` passed. Live behaviour unverified.

### 2026-11-19 — Browser timeout budget and follow-up fixes (Stage 20 partial)

Run `20261119T122953Z-7df17b` (`radiohead - there there`, `--sources all --no-cache`) after `52c6c67`. The table pasted with it repeated the previous run; the journal shows: no "not installed" errors; Beatport found the track through the headed fallback; Album of the Year and 1001Tracklists loaded. Remaining:
- Deezer (40.6 s), Discogs (36.5 s), and Genius (34.9 s) hit the 30 s adapter timeout before the manual prompt: API requests, the headless attempt, launching headed Chrome on the empty `…-direct` profile, `goto`, and the automatic wait all counted.
- RYM ran headless-configured in the already headed browser, then fell back to the same browser again; the final 403 without a body (`net::ERR_HTTP_RESPONSE_CODE_FAILURE`) was retried three times as a network error and reported as `failed`.
- WhoSampled `/radiohead/there-there/` redirected to `/Radiohead/` and was reported as `failed`.
- AllMusic returned 200 but no recognisable record; nothing was recorded about the page.
- Not changed: WFMU `ConnectTimeout`, Forced Exposure HTTP 403.

Decisions (user): browser launches and every headed request are outside the adapter timeout; fix the four smaller issues.

Changed: `BrowserSessions.use()` yields `BrowserLease(fetcher, headed)`; the client pauses the adapter timeout for headed requests, treats a headless source served headed as headed (no second fallback, `[headed]` label), and labels requests after they run. Fetchers pause the timeout while launching. Patchright returns an empty-bodied response for `ERR_HTTP_RESPONSE_CODE_FAILURE` after a recorded navigation; Nodriver returns the document status for Chrome's error page when it is 400 or more. WhoSampled reports a redirect to an artist page as `not_found`. AllMusic writes `parse.unrecognized` (URL, title, 300 body characters) before its parse error.

Verification: `uv run poe check` passed (973 offline tests, 96.75% coverage); `uv run --group docs properdocs build --strict` passed. Live behaviour unverified.

### 2026-11-19 — Browser blocks after shared sessions (Stage 20 partial)

Run `20261119T120927Z-2e3a98` (`radiohead - true love waits`, `--sources all --no-cache`) after `5d4b838`. Journal findings:
- Deezer, Discogs, and Beatport reported "Chromium for Patchright is not installed". Cause: `.env` sets `proxy=direct` for Deezer and Discogs, so `BrowserSessions` opened two browsers on one persistent profile, and Chrome refuses a second open. Patchright's launch error was reported as a missing browser, and the client dropped the step for the run (regression from `5d4b838`).
- AllMusic, Album of the Year, and Rate Your Music fell back to headed together in one window. Only AllMusic cleared (it cleared itself); AOTY and RYM waited 60 s in background tabs. The user saw no window or prompt.
- Boomkat and WhoSampled (configured headed) waited only `browser_challenge_wait`; the headed 1001Tracklists fetch (27.7 s) hit the 30 s adapter timeout.
- Not changed: Forced Exposure HTTP 403 without a recognised challenge (no escalation); the Genius HTML `goto` timeout in headless mode.

Decisions (user): a sibling persistent profile per proxy route; the manual-solve wait for every headed page.

Changed: `route_profile()` gives non-environment routes `<dir>-direct` / `<dir>-<host>-<port>`. Patchright reports a launch error as a missing browser only when the executable is absent, otherwise as `TransportError("browser launch failed: …")`, which does not drop the step. Nodriver maps only `FileNotFoundError` to a missing browser. In headed mode, a page still challenged after `browser_challenge_wait` takes a per-browser front lock, is brought to the front, logs `SOLVE_PROMPT` at WARNING, and waits `headed_challenge_wait`, all outside the adapter timeout. The CLI prints these warnings (message only) to stderr in normal runs. `Request.challenge_wait` was removed; the wait is a fetcher setting.

Verification: `uv run poe check` passed (966 offline tests); docs build passed. Live behaviour unverified.

### 2026-11-19 — Shared browser sessions and headed fallback (Stage 20 partial)

Requested after an uncached `--sources all` run in which headed sources opened a window per request and several headless sources ended as Cloudflare blocks.

Decisions (user): sessions and the fallback apply to Patchright and Nodriver; a lookup upgrades headless → headed once and never downgrades; the headed fallback waits `http.headed_challenge_wait` (default 60 s, excluded from the adapter timeout) for a manual solve; the fallback also runs without a persistent profile; `http.headed_fallback` (default true) disables it.

Changed: new `sources/_http/sessions.py` (`BrowserSessions`) lends one browser per transport, launch settings, and proxy to all clients of a lookup. It replaces `HttpResources.profile_lock` and the close-after-each-request behaviour of persistent profiles. Browser fetchers launch once under concurrent first use and accept a per-request `challenge_wait`. `HttpClient` retries a challenged headless browser step headed and keeps the source headed. `tried` lists, for example, `browser[headed]`. The blocked-cache policy signature includes the two new settings. `SourceAccess`/`SourceInfo` gain `headed_fallback`, and the access label shows `[headless → headed]`. `lookup()` closes the sessions.

Observation: headless Patchright (bundled Chromium 156, persistent context included) reports `HeadlessChrome/156…` in `navigator.userAgent` and CDP `Browser.getVersion`. Cloudflare binds `cf_clearance` to the User-Agent, so cookies solved in the headed fallback may not pass later headless runs; such sources would fall back again in each run (one shared window). Overriding the headless User-Agent is automation masking (see "Later, unscheduled") and was not implemented; configuring those sources headed is the alternative.

Verification: `uv run poe check` passed (953 offline tests, 96.70% coverage); `uv run --group docs properdocs build --strict` passed. No live lookup was run after the change.

### 2026-11-16 — Blocked source access in lookup output (Stage 20 partial)

Blocked errors now carry the source's access configuration from the same lookup, including API use, ordered HTML transports, and headed or headless browser mode. The terminal and Markdown error tables show an Access column; JSON serializes the structured `access` object. Other error kinds have an empty column. The access label is shared with `deadwax sources`, and the source details reflect one-run CLI overrides. README and source/output documentation describe the field.

Verification: `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (938 offline tests, 96.67% coverage); `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. Tests cover HTML-only and mixed API/HTML access, all output formats, and a mocked blocked lookup. No live request was made; Stage 20 qualification remains open.

### 2026-11-16 — Persistent browser profile queue timeouts (Stage 20 partial)

The user's uncached `--sources all` run (`20261116T025317Z-450422`) took 69.6 seconds and reported seven adapter timeouts. Its journal shows Discogs completing seven API requests in about one second each before opening a review page; AllMusic and Album of the Year encountered HTML challenges; Phonica, Boomkat, WhoSampled, and 1001Tracklists ended without a completed HTTP request. The configured persistent Patchright profile serializes browser fetches through a shared lock, and the former 30-second adapter deadline included time spent waiting for that lock. The deadline now pauses only for this queue wait and resumes when the browser profile becomes available. The active fetch and parser retain their timeout. This does not claim that every source can finish active work in 30 seconds; 1001Tracklists already documents `--timeout 120` for its request rate.

Verification: `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (934 offline tests, 96.66% coverage). A concurrency test waits longer than the active timeout for a shared resource and then completes within its active budget. Live lookup after the change remains unverified.

### 2026-11-16 — All source selector (Stage 20 partial)

`--sources all` now expands to every registered adapter. The existing status filter still omits disabled sources and reports sources without required credentials as skipped; `--exclude` still removes selected sources. The selector also works in `DEADWAX_DEFAULT_SOURCES` and `--exclude`. CLI help, README, and source documentation describe it.

Verification: `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (933 offline tests, 96.65% coverage); `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. No live lookup was run. Stage 20 qualification remains open.

### 2026-11-16 — Disable sources without permitted HTML transports (Stage 20 partial)

The global HTML allowlist can remove every transport of a source configured for Nodriver only, such as Norman Records. `SourcesConfig.html_transports()` now returns an empty tuple in this case; the adapter reports `disabled` with the reason `no permitted HTML transports`. Lookup omits the adapter without making a request or adding an error. `deadwax sources` shows the disabled reason and `HTML (no permitted transports)` in its access column. Sources with both API and HTML access are disabled entirely when their HTML transports are exhausted, as requested.

Verification: targeted offline tests passed (19); `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (931 offline tests, 96.65% coverage); `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. Stage 20 qualification, including live runs, build, and audit, remains open.

### 2026-11-16 — Source access display (Stage 20 partial)

`deadwax sources` now reports configured API and HTML access in pretty, Markdown, and structured JSON output. HTML transports retain their configured order; the displayed `browser` transport is named `patchright`, and Patchright and Nodriver show the configured headed or headless mode. Discogs, Bandcamp, Hard Wax, and Genius report both API and HTML access. The command does not probe sites or installed optional transports. README and source documentation describe the output and correct the default set to include Genius.

Verification: `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (928 offline tests, 96.65% coverage); `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. Stage 20 qualification, including live runs, build, and audit, remains open.

### 2026-11-16 — Stage 18 implementation, live verification pending

The user confirmed express RYM permission for automated access and chose full visible user reviews and chart positions as relations. Added the opt-in Rate Your Music adapter, browser-only default transport, URL recognition, settings, documentation, and public `secondary_genre`, `rating_votes`, and `charted_in` kinds. Synthetic HTML tests cover the extraction shape, search results, and missing page identity. The parser selectors are provisional because no real RYM page could be captured. The sandboxed direct request failed DNS resolution; an unsandboxed request reached RYM but received HTTP 403 with `cf-mitigated: challenge`. A live headed Patchright lookup of *Radiohead — OK Computer* returned `blocked` ("Cloudflare challenge (tried browser)") on the search page. Further five-record runs would hit the same challenge, so Stage 18 remains in progress; real page fixtures, blocked/not-found/version tests, and live verification remain required before completion.

`UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (912 tests, 97.00% branch coverage; format, lint, 33 import contracts, strict mypy). The strict docs build passed.

### 2026-11-16 — Stage 18 offline failure paths

Added isolated lookup tests for an empty search, a Cloudflare challenge, and a search hit for another version. The version test confirms that its genre is dropped and an `other_version` relation remains. Chart relations now name the chart separately from their position note. A live headed Patchright request to the direct *OK Computer* RYM URL also returned `blocked` ("Cloudflare challenge (tried browser)"), so bypassing search does not provide real markup. Stage 18 remains in progress pending rendered RYM search and record pages, real fixtures, and live acceptance. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (915 tests, 97.01% branch coverage; format, lint, 33 import contracts, strict mypy). No documentation changed in this continuation; the previous strict docs build remains the latest docs check.

### 2026-11-16 — Stage 18 headed manual challenge attempt

At the user's request, opened a visible Patchright Chromium window with a dedicated persistent profile at `/private/tmp/deadwax-rym-profile` for manual challenge completion. Automatic navigation to the *OK Computer* RYM page failed with `net::ERR_HTTP_RESPONSE_CODE_FAILURE`; navigating in the open browser showed Chrome's `HTTP ERROR 503` page. The user confirmed that reloading did not help. There was no challenge widget to complete and no record markup to capture. The browser process was stopped; Stage 18 remains in progress. No code changed in this attempt.

### 2026-11-16 — Stage 18 browser diagnosis

An unsandboxed direct GET to the *OK Computer* RYM URL returned HTTP 403 with `cf-mitigated: challenge` and a Cloudflare "Just a moment" page. A directly launched isolated Google Chrome showed `ERR_INVALID_HANDLE` for both RYM and `example.com`, isolating that error to the managed browser process. Opening the URL in the user's ordinary Chrome did show the Cloudflare check, but after the user attempted it the browser moved to a `__wI_challenge_id` URL and showed `HTTP ERROR 503`. The RYM album page still did not load. The site-side challenge remains the live verification blocker; no adapter code was changed.

### 2026-11-16 — Stage 18 deferred at user request

A separate visible Chrome with a DevTools connection loaded `example.com`, but its RYM album tab returned a Cloudflare challenge followed by `HTTP ERROR 503`. The user also tried navigating manually in that browser; the album stopped opening. No RYM search or record HTML was captured, so parsing cannot be qualified. The user asked to defer this source. Keep the provisional opt-in adapter and tests, leave Stage 18 deferred, and make Stage 19 the next stage on request. No further RYM retries are planned until access changes.

### 2026-11-19 — Deezer out of the default set

User request: Akamai blocks Deezer on every route, so `DEFAULT_SOURCES` now names the `core` members except Deezer instead of the `core` group. Deezer stays in `core` and runs when named (`--sources deezer`, `--sources core`, or `DEADWAX_DEFAULT_SOURCES`). README, `.env.example`, and `docs/sources.md` updated.
