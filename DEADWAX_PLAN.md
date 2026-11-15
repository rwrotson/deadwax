# deadwax v2: implementation plan and handoff journal

## Status and handoff

This is the active specification and multi-session handoff for deadwax. deadwax collects, for one track or album, what open sources know about that exact recording, with four goals: (1) texts describing its sound, (2) relations for further searches, (3) confirmation of the exact recording and version with visible discrepancies, (4) streaming links. v1 (eight sources) is complete; its plan, stage evidence, and full decision log are archived in [`plans/v1.md`](plans/v1.md).

- **Status:** v1 complete and committed. v2 source scope recorded (`## v2 sources`); v2 stages 8–20 defined; Stages 8–17 done (Boomkat and Norman Records remain access-limited).
- **Branch:** `main`. Agents never create commits on the user's behalf.
- **Working rule:** complete one stage, run its acceptance checks, append dated evidence, update the status table, report an English Conventional Commit suggestion, and stop. Resume the next stage only when the user asks.
- Read `AGENTS.md` and `docs/architecture.md` (import rules R1–R9) before code changes. After code changes run `uv run poe check`; after docs or public docstring changes also run `uv run --group docs properdocs build --strict`.
- Before changing a v1 adapter, read its rows in the decision log of `plans/v1.md`.

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
- Adapters are constructed with their settings; `status()` takes no arguments; `requires` lists setting paths (`discogs.token`) that the CLI maps to `DEADWAX_` names.
- Excluded and disabled adapters produce no error; a missing key or extra gives `skipped`; unknown names in include/exclude raise `ConfigurationError`.
- Every source has `user_agent` and `proxy` settings (`direct` bypasses the environment proxy). The CLI exposes every `SourcesConfig` section; each field is described and listed in `.env.example`.
- Default API contact is the repository URL.
- Shared adapter code lives in `sources/_base.py`, `_html`, `_http`; adapters never import each other. An adapter that grows becomes a package with its own layers contract.
- `deadwax` imports `deadwax.sources` lazily.
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

Numbering continues after v1 (stages 0–7 in `plans/v1.md`). Order: shared infrastructure first; clean APIs next, to prove it; each model addition lands in the first stage whose source needs it; sources behind bot protection or with open terms-of-service questions last, so those decisions can be made meanwhile.

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
| 18 | Not started | Rate Your Music; browser-first fetching. |
| 19 | Not started | 1001Tracklists, WhoSampled. |
| 20 | Not started | Qualification. |

Common acceptance for source stages 9–19, in addition to each stage's own:

- The adapter declares its `group`. An open-API source of the agreed default set (ListenBrainz, SecondHandSongs, KEXP, Spotify, YouTube, Genius) is added to `DEFAULT_SOURCES` in `sources/config.py` in its stage; other sources stay opt-in.
- An HTML source that searches and reads one page builds on `SearchPageAdapter` in `sources/_base.py`, or the evidence says why not.

- Fixture tests for every extraction path, and for not found, blocked, and a missing key where one applies.
- The matching gate drops a candidate of another version (tested).
- Every new setting has a description and a line in `.env.example`; the source is described in `docs/sources.md` and the README tables.
- `uv run poe check` and the strict docs build pass.
- Live runs on the five v1 check records and at least one record the source is strong on; the report separates mock-tested from live-verified behaviour.

### Stage 8: foundation

- [x] Source groups (`shops`, `press`, `catalogues`, `radio`, `streaming`, `samples`, and the v1 sources as `core`) accepted by `--sources` and `--exclude` and shown by `deadwax sources`.
- [x] The default set of enabled sources, decided with the user at the start of the stage (a full lookup would otherwise query 34 sources).
- [x] A per-lookup cap on concurrent adapters (setting), so a lookup with every source stays within rate limits.
- [x] A shared helper in `sources/_base.py` for HTML sources that search, pick a candidate through the matching gate, and read its page.

**Acceptance:** orchestrator and CLI tests for groups, the default set, and the cap; the helper tested with a fake source. **Suggested message:** `feat(sources): add source groups and a concurrency cap for v2 sources`.

### Stage 9: ListenBrainz, SecondHandSongs, KEXP

- [x] ListenBrainz by MBID: similar recordings and artists, listen counts; CritiqueBrainz reviews as `user` texts.
- [x] SecondHandSongs: original and first release, writers, covers and adaptations as directional relations.
- [x] KEXP: plays as `broadcast` relations with dates; DJ comments as texts.

**Acceptance:** covers from SecondHandSongs and MusicBrainz merge into one relation per target. **Suggested message:** `feat(sources): add ListenBrainz, SecondHandSongs and KEXP adapters`.

### Stage 10: Spotify, YouTube, SoundCloud

- [x] Spotify with client credentials: links, popularity, label, copyrights, ISRC; resolves Spotify URLs.
- [x] YouTube with a Data API key: links only (official uploads first), no facts.
- [x] SoundCloud with a user-supplied client ID: uploader descriptions, tags, counts, reposters as relations; resolves SoundCloud URLs.

**Acceptance:** missing credentials give `skipped`; YouTube contributes nothing but links. **Suggested message:** `feat(sources): add Spotify, YouTube and SoundCloud adapters`.

### Stage 11: Beatport, Juno Download

- [x] Model: BPM and key as sourced identity values with discrepancies.
- [x] Version detection: mix names (Original, Extended, Dub, Radio Edit…) mapped to versions.
- [x] Beatport from `__NEXT_DATA__`: BPM, key, subgenre, mix name, ISRC, remixers, DJ charts as relations (tested on pages saved from a browser; live run pending).
- [x] ~~Juno Download: BPM, genre, label.~~ Dropped: the store shut down.

**Acceptance:** an Extended Mix is not merged into the Original Mix; a BPM disagreement is a discrepancy. **Suggested message:** `feat(sources): add Beatport and Juno Download adapters with BPM and key`.

### Stage 12: shops I

- [x] Juno, Hard Wax, Soundohm through the Stage 8 helper: `shop` texts, genres, "also bought" as `similar` where present.
- [x] ~~Phonica~~ Moved to "Later, unscheduled" (2026-11-13, user decision): its search API answers Apache 403 without a Sucuri browser session.
- [x] Merge: `shop` texts that repeat one press release are deduplicated, keeping every source.

**Acceptance:** the same press text from two shops appears once with both sources. **Suggested message:** `feat(sources): add Juno, Hard Wax and Soundohm adapters`.

### Stage 13: shops II

- [x] Forced Exposure and Bleep: `shop` and `label` texts, genres, related releases as `similar` where present.
- [x] Repair Nodriver's false HTTP 200 on Chrome error pages; allow explicit browser path and sandbox settings.
- [x] Retry Boomkat and Norman Records through the repaired Nodriver; defer both after Cloudflare 403.

**Suggested message:** `feat(sources): add Boomkat, Norman Records, Forced Exposure and Bleep adapters`.

### Stage 14: Genius

- [x] User chose to store full lyrics.
- [x] Genius API with a token: description and annotations as texts, credits, samples, interpolations, covers, and remixes as directional relations; lyrics from HTML.

**Suggested message:** `feat(sources): add Genius adapter`.

### Stage 15: reviews I

- [x] AllMusic: review with rating and critic, moods and themes as `mood`/`theme` tags, styles, credits, similar albums.
- [x] Album of the Year: critic scores per publication, user score, genres; review links carried in the context for Stage 16, with MusicBrainz review links.

**Acceptance:** an AllMusic score from Wikipedia's ratings template and from AllMusic itself merge into one review. **Suggested message:** `feat(sources): add AllMusic and Album of the Year adapters`.

### Stage 16: reviews II

- [x] The user chose full available review text.
- [x] Press adapter: one adapter, per-site rules for Pitchfork, The Quietus, and The Wire, reading review links from the context.
- [x] Resident Advisor through its GraphQL endpoint: reviews, artist and label bios. DJ charts were discontinued by RA's site redesign and dropped from this stage.

**Suggested message:** `feat(sources): add press review and Resident Advisor adapters`.

### Stage 17: radio

- [x] Model: tags of an episode or set marked as context rather than the track's own.
- [x] NTS: episodes that played the track as `broadcast`, neighbouring tracks, episode genres as context tags.
- [x] WFMU: playlists as `broadcast`, DJ comments as texts.

**Suggested message:** `feat(sources): add NTS and WFMU adapters`.

### Stage 18: Rate Your Music

- [ ] Decide with the user on terms of service, before the stage; if declined, the stage is dropped.
- [ ] Browser-first fetching for a source that never answers plain httpx.
- [ ] Primary and secondary genres, descriptors as `descriptor` tags, rating with vote count, chart positions, user reviews.

**Suggested message:** `feat(sources): add Rate Your Music adapter`.

### Stage 19: 1001Tracklists, WhoSampled

- [ ] Decide with the user on terms of service for each, before the stage; a declined source is dropped.
- [ ] 1001Tracklists: sets as `mix` relations, supporting DJs, neighbours in sets.
- [ ] WhoSampled: samples used and sampled by with timestamp and element, covers, remixes.

**Suggested message:** `feat(sources): add 1001Tracklists and WhoSampled adapters`.

### Stage 20: qualification

- [ ] README source tiers and docs pages for every v2 source.
- [ ] Full checks, package build and wheel smoke, audit; `poe test-live` with the v2 sources.
- [ ] Manual runs on the check records with the default set and with every source; the time of a full lookup recorded.

**Acceptance:** all checks pass or blocked ones have precise reasons. **Suggested message:** `docs: document sources and qualify deadwax v2`.

### Later, unscheduled: automation masking for Cloudflare-protected sources

- [ ] Masking browser automation (stealth plugins, undetected-chromedriver, nodriver, Camoufox, fingerprint spoofing) so that Beatport and similar sources pass Cloudflare challenges that defeat httpx, curl_cffi, and plain Playwright.
- [x] Phonica (moved from Stage 12 on 2026-11-13 at the user's request): restored after a dedicated Patchright profile opened its product pages and search API in headed and headless modes. The earlier adapter remains in commit `9af10f2`, with the JSON-search changes in `plans/phonica-search.patch`.

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

### 2026-11-13 — Per-source HTML transport selection (Stage 13 preparation)

Decision: HTML sources choose an ordered list of transports. The built-in list is httpx, curl_cffi, Patchright, Nodriver, except Beatport (Nodriver first, provisionally) and Juno (curl_cffi first, live-verified in Stage 12). The global `http.escalation` setting now lists permitted optional transports. The former single-value cap is incompatible with this format.

Changed: transport selection and missing-transport fallback in the shared HTTP client; JSON clients separate from HTML clients for Bandcamp and Hard Wax; per-source `html_transports` settings, cache policy signature, configuration examples and documentation. This does not claim a successful live Beatport or Nodriver lookup.

Verification: delegated to the user in a separate environment. No check or live command was run in this session; Stage 13 remains open.

User live run (`--album "Burial - Untrue" --sources beatport,juno,soundohm,odesli,discogs,hardwax,bandcamp --no-cache`): Bandcamp, Juno, Hard Wax, and Soundohm contributed facts; Beatport failed with "Nodriver did not receive a document response"; Discogs exceeded its 30-second adapter timeout; Odesli had no streaming seed. Nodriver launched Chrome twice and emitted event-loop shutdown warnings. Follow-up code enables CDP Network events before navigation, accepts the last document response when its URL differs from the final tab URL, and lets a transport error fall through to the next configured engine. These fixes await the user's live recheck.

Local checks after the follow-up: `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (830 offline tests, 98.83% coverage; format, lint, import contracts, mypy all passed). `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. Fixture setup and the recorder now use an empty allowed-transport list in place of the removed `Escalation.NONE`. No live request was made by the agent.

User recheck after installing Patchright Chromium: Beatport remained `blocked` by Cloudflare through Patchright, curl_cffi, and httpx; Nodriver again lacked a document response. Discogs' optional reviews had the same Nodriver error, while its core lookup completed with a 60-second adapter timeout. The Nodriver transport now returns rendered HTML when CDP omits the document response event, using the response status when available and a provisional 200 otherwise; an empty navigation still fails. Offline `poe check` passed (831 tests, 98.83% coverage). Live behaviour after this change awaits the user.

Next user run (Beatport alone): Nodriver supplied HTML but Beatport rejected it for lacking `__NEXT_DATA__`; the source returned `failed`. The browser transport now reads the navigation status from the Performance API when CDP omits the response event. Beatport marks `__NEXT_DATA__` as required page state at the HTTP layer, so an incomplete page tries the next configured transport. This change awaits local checks and a live recheck.

2026-11-14 local verification: `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (833 tests, 98.78% coverage; format, lint, import contracts and mypy passed). `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. No external request was made; Beatport's live result after the page-state fallback remains unverified.

Final local pass after limiting the Performance API probe to navigations without a CDP response event: `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed again (833 tests, 98.78% coverage). The strict docs build above remains the latest docs check; no external request was made.

User live recheck on 2026-11-14 (`--album "Burial - Untrue" --sources beatport --no-cache --timeout 60`): Beatport returned `blocked` with "Cloudflare challenge (tried nodriver, browser, impersonate, httpx)". All four configured HTML transports ran; the missing-state fallback no longer ends in a parser error. Beatport facts remain live-unverified because the site refused every transport from this network.

2026-11-14 maintenance handoff (user-reported run): the CLI now omits console log handlers by default, while `--verbose` / `--debug` enables diagnostic stderr logs; run journals and configured file logging remain active. Nodriver shutdown awaits connection closure and subprocess exit before `asyncio.run()` closes its loop. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (833 tests, 98.77% coverage); `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. The user's run journal `20261114T010330Z-6310c0` shows Bandcamp's search API and HTML search at `bandcamp.com` both returned the same 8,887-byte HTTP 503 body after four httpx attempts each; the direct `burial.bandcamp.com` release page is a separate host. The agent's live retry could not resolve `bandcamp.com` in its network environment. Bandcamp direct-page recovery and the user-requested HTML-only Deezer adapter remain for the next work segment; Stage 13 source work has not begun.

2026-11-14 maintenance continuation: Bandcamp now tries a direct artist-subdomain page when both search routes fail, and accepts it only if the parsed artist, title, and kind match the query. The original search error is retained if that candidate is absent or wrong. Two offline tests cover 503 recovery and rejection of a mismatched page. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (835 tests, 98.72% coverage); `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. Live success remains unverified because the agent's network cannot resolve Bandcamp. HTML-only Deezer remains the next maintenance segment; Stage 13 source work has not begun.

2026-11-14 maintenance continuation: Deezer now uses `www.deezer.com` HTML only. URL queries and known links read the record page; search opens linked record pages and checks their identity. Embedded `__DZR_APP_STATE__` is read when present, with JSON-LD as a fallback; absent fields are not invented. The old API calls were removed. Offline Deezer tests cover album and track pages, search, version rejection, and missing data. Historical replay fixtures contain only API 403 responses, so the replay harness carries that recorded block response to HTML requests until new live fixtures can be recorded. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (831 tests, 98.59% coverage); `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. The agent could not reach live Deezer HTML from this network; search-page markup and live extraction remain unverified. Stage 13 source work has not begun.

| Date | Decision | Reason | Affected stage |
| --- | --- | --- | --- |
| 2026-11-13 | v2 source scope: all sources planned in v1 except Rough Trade, Apple Music, Traxsource, Mixcloud and BBC Sounds; YouTube for links only. | User review of what each source can give. | v2 |
| 2026-11-13 | The v1 plan is archived in `plans/v1.md`; this file carries the decisions that still apply as "Standing decisions". | Keep the active plan short for agents that read it before every session. User choice. | v2 |
| 2026-11-13 | v2 stages 8–20; numbering continues v1. Model additions land with the first source that needs them; sources with open terms-of-service questions come last and are dropped if declined. | User request for a stage breakdown. | 8–20 |
| 2026-11-13 | Default source set: `core` plus the open-API v2 sources (ListenBrainz, SecondHandSongs, KEXP, Spotify, YouTube, Genius); shops, press, scraped radio and samples sources are opt-in. Stage 8 ships `("core",)`; each of those sources joins `DEFAULT_SOURCES` in its own stage, since an unknown name in the set is a configuration error. | A full lookup would query 34 sources; open APIs are fast and within their terms. User choice. | 8, 9, 10, 14 |
| 2026-11-13 | The default set is the setting `default_sources` (`DEADWAX_DEFAULT_SOURCES`, source and group names, comma-separated); `--sources`/`include=` replaces it for one run, `--exclude` subtracts from either, and `<source>.enabled=false` still wins. | Users choose whole groups with one value. User choice. | 8 |
| 2026-11-13 | Every adapter has one `SourceGroup`; group names never equal source names (tested). Groups are expanded in the orchestrator (`expand_names`), so `include` and `exclude` take both. | One selection rule for the library and the command. | 8 |
| 2026-11-13 | `concurrency` setting, default 8: one semaphore per lookup across passes; an adapter's timeout starts when it gets a slot. | Lookups with many sources stay within rate limits without timing out queued sources. User choice of the default. | 8 |
| 2026-11-13 | Counts are `Metric` facts (`kind` `listens`/`listeners`, `value`, `scale`) in `Partial.metrics` and `Dossier.metrics`, with `Capability.METRICS`; a source's counts are never combined with another's. | ListenBrainz counts now, Spotify popularity and SoundCloud counts in Stage 10. User choice. | 9, 10 |
| 2026-11-13 | Radio hosts' notes are `TextKind.BROADCAST` texts (author the host, publication station and program). | Keeps them apart from editorial copy; NTS and WFMU reuse it in Stage 17. User choice. | 9, 17 |
| 2026-11-13 | Relations to one target merge across sources; the kept target takes missing artist, date and URL and the union of IDs from the others. `broadcast` and `mix` targets also differ by date. | One relation per cover with both sources; one relation per play, not per program. | 9 |
| 2026-11-13 | MusicBrainz work lookups include `artist-credits`, so covers listed by a work name their artist. Only the work entries of the MusicBrainz fixtures were re-fetched. | Without artists, MusicBrainz covers never merged with SecondHandSongs covers. | 9 |
| 2026-11-13 | SecondHandSongs is read through `api.secondhandsongs.com` (the website answers a Cloudflare challenge); songs only; covers carry no dates; a later recording by the original artist is `other_version` of the first performance and shares its covers. Optional `secondhandsongs.api_key`. | Cover dates cost one request per cover at about 10–20 requests a minute; SecondHandSongs calls Tim Buckley's 1970 "Song to the Siren" a cover of his 1968 TV performance. | 9 |
| 2026-11-13 | KEXP reads the latest 25 plays by recording MBID, else by artist and title; albums always by artist and album title. | The API ignores `release_group_id` and returns the station's latest plays (verified live; the matching gate dropped them). | 9 |
| 2026-11-13 | ListenBrainz, SecondHandSongs and KEXP are JSON APIs, so they build on `HttpAdapter`, not `SearchPageAdapter`. | The helper is for HTML search and page sources. | 9 |
| 2026-11-13 | Cover and sample check records: `--track "Tim Buckley - Song to the Siren"` (covers) and `--track "Kanye West - Stronger"` (samples). | User choice. | 9–19 |
| 2026-11-13 | A marker or MusicBrainz comment "explicit" (or "explicit version") means the original; "clean" stays an edit. | "Explicit" names the uncensored album version; as an edit it made MusicBrainz reject the canonical recording of "Kanye West - Stronger". | 9 |
| 2026-11-13 | `SearchPageAdapter` order: query URL of its service, a page of its service from earlier passes, then search. `pick_hit` takes the first `MATCH`, else the first `other_version` hit, which the merge turns into a relation and a version discrepancy; `NO_MATCH` hits are never read. | Another version's page still informs identity, and the merge gate already handles it. | 8, 12–19 |
| 2026-11-13 | SoundCloud reads a user-supplied `soundcloud.client_id` (secret query parameter); without it the source is `skipped`. deadwax never extracts the web client's ID from soundcloud.com's JavaScript. A refused request is `failed` and asks whether the ID is stale. SoundCloud stays opt-in. | SoundCloud registers no new API apps; extracting the ID is unofficial access. The web client's ID changes now and then, so the user replaces it by hand. User choice. | 10 |
| 2026-11-13 | Copyright lines are identity values: `RecordCandidate.copyrights` → `Identity.copyrights` (`Sourced[str]`), merged by `normalize_copyright` (℗ and © kept apart; `(P)`, `℗`, `Copyright` written alike). Spotify gives its type as ℗/©, SoundCloud `p_line`/`c_line`. | Spotify and SoundCloud both give them; they help tell releases and reissues apart. | 10 |
| 2026-11-13 | `MetricKind` gains `popularity` (Spotify, scale 100), `likes` and `reposts` (SoundCloud); SoundCloud plays are `listens`. `RelationKind.REPOSTED_BY` (target an artist entity) holds SoundCloud reposters. The uploader's description is a `label` text with the uploader as author. | Counts stay per source (Stage 9 decision); reposts are vouching, not similarity. | 10 |
| 2026-11-13 | YouTube is a links-pass source whose partial carries links only, no candidate: uploads are filtered in the adapter by the matching gate (Topic channel names the artist; others need "Artist - Title"; only `MATCH`), at most three, Topic channel first, then a channel named like the artist or its VEVO channel. | The product contract: YouTube contributes nothing but links, and a links-only partial bypasses the merge gate. | 10 |
| 2026-11-13 | `SpotifyAdapter` comes first in `ADAPTERS`, so it resolves Spotify URLs when ready; without credentials MusicBrainz still does. Its token comes from a second client with the same rate limits and no response cache, once per adapter; it is not refreshed. | A token lives an hour, an adapter one lookup; a cached token would outlive itself. A `store` flag on `HttpClient.request` was tried and dropped (argument limit). | 10 |
| 2026-11-13 | A "<Name> Edit" marker (a DJ's edit, such as "Kode9 Edit") is not detected as a version; only exact edit forms are. Left to Stage 11's mix-name work. | Found while testing SoundCloud edits; Stage 11 owns version detection of mix names. | 11 |
| 2026-11-13 | SoundCloud reposters become relations only when verified or with at least 1,000 followers, from the first 50; search hits are ordered official first (distributor metadata, then an uploader named like the artist); the candidate's date is the upload's `release_date` only. | Live: of 20 reposters of "Paranoid Android" one had over 1,000 followers; re-uploads won the search and their upload dates became date discrepancies. | 10 |
| 2026-11-13 | YouTube treats "(Full Album …)" and a bare "(1997)" as upload notes. | Search with `type=playlist` never returns Topic channels' album playlists, only listeners' "full album" ones (live, "OK Computer"). | 10 |
| 2026-11-13 | Every credential setting has instructions in README's "Credentials" section (rule in AGENTS.md). | User request. | all |
| 2026-11-13 | Beatport is read from the `__NEXT_DATA__` state of its pages through `SearchPageAdapter` and the escalation ladder; the agent builds it on hand-made pages and the user records fixtures and runs live checks. | Plain requests get a Cloudflare 403; the agent's curl_cffi probe was refused by Claude Code's safety classifier. User choice. | 11 |
| 2026-11-13 | Juno Download is plain HTML through `SearchPageAdapter`, built on hand-made pages; the user records and verifies it through `junodownload.proxy`. | The site resets TLS connections from the agent's network (likely a regional block). User choice. | 11 |
| 2026-11-13 | `VersionKind.EXTENDED` (Extended/Club Mix, 12" Version) and `VersionKind.DUB` (plain Dub, Dub Mix); Radio, Single, Album, 7" Edit stay `edit`; "<Name> Edit"/"<Name> Re-Edit" and "<Name> Dub" are `remix` with the name as detail. | Extended and Radio Edit were both `edit` and merged; a DJ's edit is someone else's rework. User choice. | 11 |
| 2026-11-13 | Two remixes by one remixer are different versions when one names a cut the other does not (`extended`, `radio`, `dub`, `instrumental`); "Club Mix" is not a cut, so Todd Terry's Club Mix stays his Remix. | "Todd Terry Extended Remix" matched "Todd Terry Remix" by detail similarity. | 11 |
| 2026-11-13 | `RecordCandidate.bpm`/`key` → `Identity.bpm` (`Sourced[float]`) and `Identity.key` (`Sourced[str]`). Tempos agree when they round to the same whole beat; keys by `normalize_key` (pitch class and mode; enharmonics, Camelot and Open Key folded), unknown notations by their text. Disagreements are `bpm`/`key` discrepancies. | Stage 11 acceptance; Beatport and Juno print keys and tempos differently. | 11 |
| 2026-11-13 | `junodownload.com` is service `junodownload` (was `juno`), adapter and settings `junodownload`; `juno` is left for the Stage 12 shop at juno.co.uk. `IdKind.BEATPORT_TRACK`/`BEATPORT_RELEASE` and URL rules for Beatport track and release pages and Juno Download product pages (albums). | Two Juno sources with different pages. | 11, 12 |
| 2026-11-13 | DJ charts (`charted_by` relations) are not added in Stage 11. | They are probably fetched by the page after load, not in `__NEXT_DATA__`; without a recorded page their shape is unknown. Revisit after the user's recording, or with Resident Advisor in Stage 16. | 11, 16 |
| 2026-11-13 | Beatport and Juno Download join collaborators with " & ". | `artist_similarity` normalizes away commas before `split_artists` looks for them, so "Burial, Kode9" does not match "Burial" (0.67); " & " does (0.9). The comma case is a core bug, not fixed in this stage. | 11 |
| 2026-11-13 | Juno Download is dropped: its adapter, settings, URL rule and docs are removed; `junodownload.com` stays in `_SERVICES` so old links name their service. | The store has shut down (user report, with a Reddit thread on r/DJs). User choice. | 11 |
| 2026-11-13 | Beatport fixtures are pages the user saved from a browser, trimmed by `scripts/beatport_pages.py`: the anonymous session (it holds an access token) and translations are dropped, query lists cut to 12 items, and the script refuses output that still holds a token. | The agent cannot fetch Beatport; saved pages are the only real data. | 11 |
| 2026-11-13 | Beatport reads fixed places of the page state, not a walk over it: `pageProps.track` with the `track-<id>-charts` query, `pageProps.release`, and the `search-tracks`/`search-releases` queries. Remixers are the `artists` of type Remixer; the sub-genre sits in `genre.sub_genre`; the track's date is its release's `release_date`. URLs are built as `/track/<slug of name>/<id>` (search results carry no slug). | Real pages hold up to 173 recommended tracks and releases, which a walk would mistake for the record. | 11 |
| 2026-11-13 | DJ charts are `charted_by` relations (`EntityType.CHART`, the DJ as the target's artist, the publish date). Supersedes the earlier deferral. | Track pages prefetch the charts that list the track. | 11, 16 |
| 2026-11-13 | "intro" is a cut word too: "Todd Terry Remix - Intro" is not the Todd Terry Remix. | Seen in Beatport's search results. | 11 |
| 2026-11-13 | Stage 11 is Done with Beatport tested only on pages saved from a browser; its facts are not live-verified. | The user's runs with the full escalation ladder met a Cloudflare challenge on httpx, curl_cffi and Playwright; nothing else can be verified from this network. User choice. | 11 |
| 2026-11-13 | Masking browser automation to pass Cloudflare is recorded as an unscheduled later item, not a stage; agents do not implement it. Alternatives discussed: the user's `cf_clearance` cookie (grey, not recommended), paid bypass services (declined), importing pages the user saved (honest, manual), Beatport API v4 (needs partner access), BPM and key from Deezer's `bpm` or GetSongBPM (to be checked). | The user's live runs: Beatport answered a Cloudflare challenge to httpx, curl_cffi, and Playwright. User request to record it. | later |

| 2026-11-13 | Stage 12 builds Hard Wax and Soundohm on live pages; Juno and Phonica on pages the user saves from a browser, verified live by the user. | Access checked before coding: Hard Wax and Soundohm answer plain requests; Juno answers a Cloudflare challenge; Phonica's server ends the TLS handshake with an internal-error alert through the user's proxy (curl and httpx alike). User choice. | 12 |
| 2026-11-13 | Hard Wax is searched through its JSON Feed (`/feeds/search.json?find=`), whose items list each release's tracks as "Artist: Title"; a track is read from its release's page. Product URLs drop `?focus=`, which switches the page's description to a format's. Store sections are `genre` tags except "CDs", "Downloads", "Label Catalog", "Merchandise". | The feed is an official, stable search; page CSS classes are obfuscated, so pages are read by ids, link targets and meta tags. | 12 |
| 2026-11-13 | Soundohm is albums only (product pages list no tracks); its "Related products" are not `similar` relations. | Related products for Burial's Untrue were unrelated label-mates, not bought-together lists. | 12 |
| 2026-11-13 | Shop and label texts are deduplicated together: equal after normalization, or one cut short with an ellipsis contained in the other, or both at least 20 words with 80% of the shorter one's word 5-grams in the other. The longer body is kept; the kind is `label` when any copy is one; other texts and short copies merge only when equal. Helpers `strip_ellipsis` and `shingle_overlap` in `core.normalize`. | Shops reprint one press release, sometimes cut short or with an extra line; Bandcamp has it as the label's text. User choice of the rule. | 12 |
| 2026-11-13 | Juno is built on Firefox view-source pages the user saved; it reads microdata (`byArtist`, `name`, `reviewBody`, `genre`), the product facts, Juno tags, and the tracklist; search results list tracks, so tracks are found on their release (helper `track_on_release` in `sources/_base.py`, shared with Hard Wax). No `similar` relations: "People also bought" is loaded by scripts. | The agent's plain requests get a Cloudflare challenge. | 12 |
| 2026-11-13 | `scripts/beatport_pages.py` becomes `scripts/saved_pages.py --shop beatport|juno|phonica`: Chrome and Firefox view-source pages; Beatport keeps its state trimming (fixtures regenerate byte for byte); shops keep the canonical link, Open Graph tags, and the blocks the parser reads, without scripts, styles, SVG, and forms; output with session data is refused. | One tool for every source built on saved pages. | 11, 12 |
| 2026-11-13 | Phonica is `phonicarecords.com` (`phonica.co.uk` does not exist), behind a Sucuri/CloudProxy JS challenge; built on saved pages. `sucuri_cloudproxy_js` is a challenge marker, so such a page is `blocked`, not an empty search. | Access check; user choice. | 12 |
| 2026-11-13 | Phonica moves from Stage 12 to the unscheduled blocking item; its adapter is kept in commit `9af10f2` and `plans/phonica-search.patch`, not in the tree. | Its search API answers Apache 403 without a Sucuri browser session; product pages answer a Sucuri challenge. User decision. | 12, later |

Changed:

- Core: `SourceGroup`, a `group` on the `Adapter` protocol, `group` and `default` on `SourceInfo`, `expand_names()`, and `LookupOptions.concurrency` with a per-lookup semaphore taken before the adapter timeout starts.
- Sources: `default_sources` and `concurrency` in `SourcesConfig`; every v1 adapter is in `core`; `lookup()` runs `default_sources` without `include`; `describe_sources()` fills `group` and `default`; `SearchHit`, `pick_hit()`, and `SearchPageAdapter` in `_base.py`.
- CLI: `DEADWAX_DEFAULT_SOURCES` (comma-separated, `NoDecode`) and `DEADWAX_CONCURRENCY`; `deadwax sources` shows group and default columns and reports an unknown name in the default set as a usage error; help texts name groups.
- Docs: `.env.example`, `docs/sources.md` (groups, default set, cap), `docs/output.md`, README.

Commands and outcomes:

- `uv run poe check`: format, lint, 18 import contracts kept, mypy strict clean, 597 tests passed, 99.26% branch coverage.
- `uv run --group docs properdocs build --strict`: built without warnings.
- Mock-tested: group include/exclude/mix and unknown names (orchestrator); the cap with 2 and unlimited, and a queued adapter not timing out; the default set and `include` replacing it (replayed `apple_url`); `describe_sources` groups and default flags; no source named like a group; `default_sources` parsing from a string, a list, the environment and TOML; CLI columns and exit 2; `SearchPageAdapter` with a fake source: search → pick → page, relative URL joined, resolved URL and earlier-pass link skip the search, no key and no match give `not_found`; `pick_hit` preference.
- Live-verified: `deadwax --album "Burial - Untrue" --sources core --exclude bandcamp` and `deadwax --track "Burial - Archangel"` returned identities from the core sources with no Bandcamp facts in the first (28 s); Deezer and Discogs were `blocked` on this network, as in v1. `DEADWAX_DEFAULT_SOURCES=nonsense` and `--sources shopz` exit 2 listing sources and groups. No v2 source exists yet, so `SearchPageAdapter` is not live-verified.

Remains: nothing for Stage 8.

### 2026-11-13 — Stage 9 evidence

Access checked live before coding: ListenBrainz popularity (POST), labs similar recordings and artists, CritiqueBrainz reviews; SecondHandSongs website behind a Cloudflare challenge, its `api.` host plain JSON without a key; KEXP plays and shows keyless, `recording_id` and `artist` + `song`/`album` filters work, `release_group_id` is ignored.

Changed:

- Core: `Metric`, `MetricKind`, `Partial.metrics`, `Dossier.metrics`, `Capability.METRICS`, `TextKind.BROADCAST`; merge keeps metrics per source, merges relations per target filling the target, and keys broadcasts and mixes by date; Markdown and pretty output have a Metrics section. `deadwax` exports `Metric`, `MetricKind`, `SecondHandSongsSettings`.
- Sources: packages `listenbrainz`, `secondhandsongs`, `kexp` (adapter | parse | models, each with an R8 contract, in the R4 adapter row); rates 2, 0.25, 2; `DEFAULT_SOURCES = ("core", "listenbrainz", "secondhandsongs", "kexp")`; MusicBrainz work lookups add `artist-credits`.
- CLI settings, `.env.example`, `docs/sources.md`, `docs/output.md`, `docs/architecture.md`, API reference index, README tables.
- Fixtures: the three sources recorded for every scenario (others replayed); new scenarios `siren_covers`, `stronger_samples`, `reckoner`; MusicBrainz work entries re-fetched with artist credits.

Commands and outcomes:

- `uv run poe check`: format, lint, 21 import contracts kept, mypy strict clean, 621 tests passed, 99.16% branch coverage.
- `uv run --group docs properdocs build --strict`: built without warnings.
- `uv run poe test-live`: 22 passed (7 min 15 s).
- Mock-tested: every ListenBrainz path (track, album, missing MBIDs, zero and null counts, user and republished reviews, empty review bodies, dates); SecondHandSongs original with covers, writers and adaptations, cover with the dated original, own later version, album, API key header, no key / no hit / 404, another version's candidate dropped by the merge with a version discrepancy; KEXP by recording ID, by text, album by text despite a release group ID, other-version and air-break plays dropped, show-less plays, comment splitting, playlist URLs; merge of metrics, relation filling, dated broadcasts; renderers. No blocked case: none of the three answered a challenge.
- Acceptance, replayed: "Tim Buckley - Song to the Siren" gives one `covered_by` relation per target, 13 of them with both MusicBrainz and SecondHandSongs; Paranoid Android 19.
- Live-verified (`--no-cache`, default set): Song to the Siren 23 s (13 merged covers, two SecondHandSongs writers including Larry Beckett, ListenBrainz counts, 2 KEXP plays); Reckoner 23 s (25 plays, 16 host comments); Paranoid Android 24 s (19 plays, 23 comments, BBC review via CritiqueBrainz); ESTADO DE BIENESTAR 4 s (ListenBrainz and KEXP `not_found`, SecondHandSongs nothing for an album); Huerco S. 38 s (release-group counts, similar artists, KEXP plays after the album fix); Кино 22 s (counts, similar, four SecondHandSongs writers and one relation); Todd Terry remix 25 s (SecondHandSongs `not_found`, still `remix_of` Missing); Untrue 19 s (counts, a CritiqueBrainz review, 25 KEXP plays); Stronger 25 s (12 SecondHandSongs relations, 4 merged covers).

Found, not fixed (outside the stage): MusicBrainz picks an obscure recording of "Kanye West - Stronger" because `core.versions` classifies the disambiguation "explicit" as an `edit`, so the canonical recording counts as another version. The chosen recording has no sample relations or ListenBrainz counts. The `stronger_samples` scenario records this state.

Remains: nothing for Stage 9.

### 2026-11-13 — fix: "explicit" is the original version

Changed: `core.versions` classifies "explicit" and "explicit version" as `original` (it was `edit`); tests for "(Explicit)", "[Clean]", and the MusicBrainz comment "explicit"; `stronger_samples` re-recorded live for every source; a replayed test for it.

Commands and outcomes: `uv run poe check` passed (625 tests, 99.16% branch coverage); no other scenario changed. Live-verified: `deadwax --track "Kanye West - Stronger" --no-cache` resolves to recording `8009d470…` (2007-08-13), with `samples` Daft Punk "Harder, Better, Faster, Stronger", mash-ups as `sampled_by`, and ListenBrainz counts. iTunes reports `not_found` for the Apple Music ID MusicBrainz gives (`1445288542`); not investigated.

### 2026-11-13 — run journal (out of stage, requested by the user)

Decision: every CLI call, and any library run that opts in, leaves a structured journal so corner cases (errors, wrong narrowing, blocked sources) can be found across history and their cause read from the log. One JSON Lines file of events per run under `<log dir>/runs/<day>/`, a one-line summary per run in `<log dir>/runs.jsonl`, HTTP metadata only (sha256 and size instead of bodies), on by default in the CLI, a `deadwax runs` command to list and show runs.

- R5 gains `events` (`trace()`, `trace_scope()`, `TraceFilter`) at the bottom, next to `errors`. Core and sources emit DEBUG events with fields under `record.deadwax`: `match.compare` (scores, verdict, failed checks), `search.pick`, `search.ranked`, `lookup.selected`, `lookup.resolver`, `lookup.kind_adopted`, `pass.start`, `adapter.end`, `merge.reference`, `merge.judge`, `http.request`, `http.retry`, `http.challenge`, `http.step_dropped`. `trace()` returns at once when nothing listens at DEBUG.
- `deadwax.logs.run_journal()` is public and opt-in; `lookup()` never writes files. Concurrent journals in one process write separate files: one router handler dispatches by a run-id context variable. While a journal is open the `deadwax` logger is at DEBUG and does not propagate; a forwarding handler passes the application's handlers only the records at the level they had before.
- `deadwax.logs` now imports public names from `deadwax`. Import-linter counts the deferred `deadwax → deadwax.sources` import as a dependency, so R1 and the logs R6 contract ignore that one edge; `tests/test_package.py` checks that importing `deadwax.logs` loads neither `deadwax.sources` nor httpx.

### 2026-11-13 — Stage 10 evidence (in progress)

Exploration: no recorded scenario has a YouTube or SoundCloud link. Odesli pages list both platforms with empty URLs, and MusicBrainz has no such URL relations for them. A read-only probe of soundcloud.com's scripts was refused by the agent's safety check; that led to the client ID decision.

Changed:

- Core: `MetricKind.POPULARITY|LIKES|REPOSTS`, `RelationKind.REPOSTED_BY`, `IdKind.SOUNDCLOUD`, `copyrights` on candidate and identity with `normalize_copyright` (exported), a SoundCloud track URL rule (sets leave the kind to the resolver), copyright lines in Markdown and pretty output.
- Sources: `SpotifySettings`, `YouTubeSettings`, `SoundCloudSettings` (exported from `deadwax`); rates 2, 1, 1; `DEFAULT_SOURCES` adds `spotify`, `youtube`; package `spotify` and `soundcloud` (R8 contracts), module `youtube`; R4 row; adapter order.
- `.env.example`, CLI settings, `docs/sources.md`, `docs/output.md`, `docs/architecture.md`, API reference index, README tables and tree; `scripts/record_fixtures.py` hosts, `client_id` as a secret parameter, recorded Spotify tokens replaced by a stand-in, stand-in credentials for replayed sources that have fixtures.

Commands and outcomes so far:

- `uv run poe check`: format, lint, 23 import contracts kept, mypy strict clean; 715 passed, 1 failed (`test_mainstream_track`: Spotify and YouTube are now in the default set and `skipped` without fixtures), 99.02% branch coverage.
- `uv run --group docs properdocs build --strict`: built without warnings.
- Mock-tested (hand-made responses): Spotify search, Spotify URL, link from an earlier pass, ISRC and UPC lookups, album search, other version → `other_version` + version discrepancy through `merge`, not found, refused credentials, token never cached, missing credentials `skipped`; YouTube ranking, links-only partial, other versions dropped, album playlists for a URL query, refused search with the key redacted, missing key; SoundCloud search, set URL, playlist and user pages refused, link from an earlier pass, bootleg → `other_version`, not found, refused client ID with the ID redacted, missing ID; copyright merge, normalization and rendering; SoundCloud URL rules.
- Not yet live-verified: no Spotify, YouTube, or SoundCloud credentials in `.env`.

Live access check (2026-11-13, keys added by the user): a Spotify development-mode app gets no `popularity`, `preview_url`, or album `label`, and search allows at most `limit=10` (`20` is "400 Invalid limit"); ISRC, UPC, dates, and copyrights come. YouTube search works with the key; SoundCloud `resolve`, `search/tracks`, `search/albums`, and reposters work with the client ID, and users carry `followers_count` and `verified`. The docs were corrected to what Spotify actually gives.

Then changed: SoundCloud reposter filter, official-first ranking and release-date-only dates; YouTube full-album notes; `soundcloud_url` scenario; the recorder runs every group (`include=ALL_GROUPS`) so opt-in sources get fixtures; `fast_config` stand-in credentials; replayed tests for Spotify resolving its URLs (and MusicBrainz without credentials), YouTube links, the SoundCloud URL; live tests read the new credentials and add SoundCloud; README "Credentials" section and its rule in AGENTS.md.

Fixtures: Spotify, YouTube, and SoundCloud recorded live for all 13 scenarios; Odesli re-recorded for `huerco_s`, `missing_remix`, `bandcamp_url`, `discogs_url`, `siren_covers` (its seed is now Spotify's link); `soundcloud_url` recorded live for every source. Spotify tokens are stored as a stand-in; a scan found no credential value in any fixture.

Commands and outcomes:

- `uv run poe check`: format, lint, 23 import contracts kept, mypy strict clean, 720 passed, 99.09% branch coverage.
- `uv run --group docs properdocs build --strict`: built without warnings.
- `uv run poe test-live`: 21 passed, 1 failed (`jason_gibbs_starlings`: MusicBrainz answered HTTP 503, the known busy server); no new source `failed` in any of the 22 lookups (9 min 36 s).
- Mock-tested: the paths listed above; no blocked case, as none of the three answered a challenge.
- Live-verified (`--no-cache`): with `--sources core,catalogues,radio,streaming` Paranoid Android 31 s (Spotify and SoundCloud ISRC and ℗/© lines merged, Topic and official YouTube uploads, SoundCloud counts), ESTADO DE BIENESTAR 9 s (all three `not_found`), Huerco S. 28 s (Spotify album, two YouTube album playlists, SoundCloud `not_found`), Кино 31 s (Spotify `no_match` for "Kino, Viktor Tsoi" under the standing non-Latin rule; SoundCloud found), Todd Terry remix 33 s (Spotify compilation track, official SoundCloud club mix, three YouTube uploads), Burial "Archangel" 34 s. Default set without `--sources`: Paranoid Android 31 s, "Burial - Untrue" 30 s, Archangel 32 s, only Deezer and Discogs `blocked` as before.

Observed, not changed: Burial has no official SoundCloud upload, so a listener's re-upload is the record's match and its counts are that upload's (they carry its URL). Spotify's strict `track:"…" artist:"…"` search finds nothing for several library tracks; a plain search found nothing better. Discogs `other_version` relations list `discogs` once per merged release in `sources` (v1 behaviour, outside the stage).

Remains: nothing for Stage 10.

### 2026-11-13 — Stage 11 evidence (implemented, awaiting live verification)

Access checked before coding: `www.beatport.com/search/tracks` answers plain curl with HTTP 403 and a Cloudflare page (robots.txt 200); a curl_cffi probe by the agent was refused by Claude Code's safety classifier (bot-check circumvention), so the agent neither recorded nor live-checked Beatport. `www.junodownload.com` resets the TLS handshake from this network (`SSL_ERROR_SYSCALL`).

Changed:

- Core: `VersionKind.EXTENDED|DUB`; exact mix-name rules and named edits in `versions`; cut words in `matching.same_version`; `normalize_key` (exported from `deadwax.core`); `bpm`/`key` on `RecordCandidate` and `Identity` with consensus and discrepancies in `merge`; BPM and key rows in Markdown and pretty output; `IdKind.BEATPORT_TRACK|BEATPORT_RELEASE` and URL rules (Beatport track/release, Juno Download product).
- Sources: packages `beatport` and `junodownload` (adapter | parse | models, R8 contracts, R4 row), both `SearchPageAdapter`, group `streaming`, opt-in, rate 0.5; service `junodownload`; added after SoundCloud in `ADAPTERS`; recorder hosts.
- `.env.example`, CLI settings, `docs/sources.md`, `docs/output.md`, `docs/architecture.md`, API reference index, README tables and tree.
- Fixtures: Odesli and SoundCloud re-recorded live for `missing_remix` only (no credential value in them). Reason: iTunes now accepts the exact "Missing (Todd Terry Remix)" instead of "Club Mix / US Radio Edit", so Odesli seeds from that Apple link (song.link: not found) and SoundCloud's live search changed. `test_remix_is_not_merged_with_the_original` no longer expects an `artist` discrepancy: it came from the wrongly accepted iTunes track credited to "Everything But the Girl & Todd Terry".

Commands and outcomes:

- `uv run poe check`: format, lint, 25 import contracts kept, mypy strict clean, 784 passed, 99.07% branch coverage.
- `uv run --group docs properdocs build --strict`: built without warnings.
- Mock-tested (hand-made pages; Beatport's state shape and Juno's selectors are from memory, not from recorded pages): mix-name versions and matching (Extended vs Original, Radio Edit vs Extended, Dub, named edits, remix cuts, Club Mix); key notations; BPM agreement within a beat and a BPM discrepancy; the acceptance case through `merge` and through each adapter (an Extended mix hit becomes `other_version` with a version discrepancy and contributes no BPM or tags); Beatport track and release search, catalogue and search-service field names, track and release URLs, a link from an earlier pass, remixers, genre and sub-genre, not found, Cloudflare challenge → `blocked`, pages without state; Juno Download releases and tracks from search, tracklist tempo and artists, implausible tempo, album and product URL, release missing the track, no label, challenge → `blocked`, dates.
- Live-verified: only the default set (Beatport and Juno Download are opt-in): `deadwax --track "Everything but the Girl - Missing (Todd Terry Remix)" --no-cache` — Spotify's "Todd Terry Remix / Radio Edit" is now an `other_version` relation with a version discrepancy; Odesli `not_found` for the iTunes seed; Deezer and Discogs `blocked` as before. Beatport and Juno Download are not live-verified.

Observed, not changed: SoundCloud accepts "Missing (Todd Terry Lite Mix)" for the Todd Terry Remix (remix details similar enough; "lite" is not a cut word). Collaboration credits joined with ", " (Spotify) are not split by the matching gate (decision row above).

### 2026-11-13 — Stage 11: Beatport on saved pages, Juno Download dropped

Juno Download has shut down (user report); its adapter and references were removed. The user saved six Beatport pages from a browser (view-source tab): track and release search for "Everything but the Girl Missing", two track pages (1331132, 27201133), two release pages (4075859, 7657829). Their state differed from the hand-made guess in every structural point (decision rows above), so the models and parser were rewritten against them, and DJ charts were added.

Commands and outcomes:

- `uv run python scripts/beatport_pages.py --name … <saved pages>`: six fixtures in `tests/fixtures/beatport/pages/` (13–66 KB); a scan for `access_token` and `eyJ` finds nothing.
- `uv run poe check`: format, lint, 24 import contracts kept, mypy strict clean, 774 passed, 99.10% branch coverage.
- `uv run --group docs properdocs build --strict`: built without warnings.
- Tested on the saved pages: track search → "Todd Terry Remix - Radio Edit" with 124 BPM, A Minor, ISRC, Virgin Records 542 6165, Pop, two `charted_by` relations (Pete Tong, Thomas Bogdan); a query for the Todd Terry Remix reads another mix, which `merge` keeps out as `other_version` with a version discrepancy; CL McSpadden as a remixer credit, not an artist; release search → "Nothing Left To Lose" with barcode and Four Tet as remixer; release URL; earlier-pass link; no match; empty search; challenge → `blocked`; malformed pages.
- Not live-verified: deadwax has not fetched Beatport itself (Cloudflare; the agent may not run the escalation ladder against it).

Live runs (2026-11-13, `--sources core,beatport --no-cache`, `DEADWAX_HTTP__ESCALATION=none`): a run with the escalation ladder was refused to the agent by Claude Code's safety classifier (bot-check circumvention), so Beatport was checked only without it.

- Missing (Todd Terry Remix) 24 s, Paranoid Android 23 s, ESTADO DE BIENESTAR 8 s, Huerco S. 18 s, Кино 20 s; every run exited 0 and found its record as before.
- Beatport: `blocked` ("Cloudflare challenge (tried httpx)") in all five; the run journal shows one request, the challenge detected, the adapter ending after about 2 s with no retries; no other source was affected.
- Other errors as in earlier stages: Deezer (Akamai) and Discogs review pages (Cloudflare) `blocked`; Odesli `not_found` for the remix; iTunes and Odesli `no_match` for Кино under the non-Latin rule.
- Version gate: the remix stays a remix with `version` and `date` discrepancies and the original as `other_version`. The other `other_version` relations of Paranoid Android, Huerco S. and Кино are Discogs pressings of the master (v1 behaviour); "Club Edition" is not read as a version. Paranoid Android's 2021-10-21 date is Bandcamp's upload date (v1 behaviour, kept as a discrepancy).
- Not live-verified: Beatport's facts (BPM, key, genres, charts) through deadwax itself.

Live runs by the user with the escalation ladder (2026-11-13, runs `20261113T141548Z-15ecf1`, `…141624Z-9c5087`, `…141702Z-fa0497`; read by the agent from the run journal): Missing (Todd Terry Remix) 31 s, Paranoid Android 37 s, "Burial - Archangel" 28 s. Beatport was `blocked` in all three: the search page answered a Cloudflare challenge to httpx, curl_cffi impersonation, and the Playwright browser in turn ("tried httpx, impersonate, browser"), about 12 s per lookup. The other sources answered as in the agent's runs. Beatport's facts are therefore not live-verified, and deadwax cannot read Beatport from this network with the transports it has.

Remains for Stage 11 (user): `uv sync --all-groups --all-extras`, then the five v1 check records and a dance record with `--sources core,beatport --no-cache` and the escalation ladder on (the default). If Beatport is `blocked` with curl_cffi too, decide whether it needs the browser step. Then the stage is marked Done.

Closed (2026-11-13, user decision): Stage 11 is Done. Beatport's extraction is mock-tested on saved pages; live lookups end `blocked` on every transport, so its facts are not live-verified.

### 2026-11-13 — Stage 12 evidence (Hard Wax, Soundohm, deduplication; Juno and Phonica pending)

Access (through the user's proxy, before coding): Hard Wax search page and JSON feed 200; Soundohm search (`/search?query=`; `?q=` redirects home) and product pages 200 with JSON-LD; Juno 403 "Just a moment…" (Cloudflare); Phonica TLS alert `internal error` from curl and httpx. Bypassing the proxy was refused to the agent.

Changed:

- Core: Hard Wax (`/<id>/…`) and Soundohm (`/product/<slug>`) URL rules (albums, no IDs); shop and label text deduplication in `merge` (`_merge_copies`, `_combine_texts`, copy kinds share one exact key); `strip_ellipsis`, `shingle_overlap` in `normalize`.
- Sources: packages `hardwax` (adapter | parse | models) and `soundohm` (adapter | parse), both `SearchPageAdapter`, group `shops`, opt-in, rate 0.5; services `hardwax`, `soundohm`, `juno`, `phonica` in `_SERVICES`; added after Beatport in `ADAPTERS`; recorder hosts; R4 row and R8 contracts.
- `.env.example`, CLI settings, `docs/sources.md`, `docs/output.md`, `docs/architecture.md`, API reference index, README tables and tree.
- Fixtures: trimmed pages in `tests/fixtures/{hardwax,soundohm}/pages/` (meta tags or JSON-LD plus the product block); Hard Wax and Soundohm recorded live for all 13 scenarios, other sources replayed. The recorder also sent one plain request per scenario to Beatport, which had no scenario fixtures (403 Cloudflare each); those files were deleted, not kept.

Commands and outcomes:

- `uv run poe check`: format, lint, 26 import contracts kept, mypy strict clean, 812 passed, 99.08% branch coverage.
- `uv run --group docs properdocs build --strict`: built without warnings.
- Mock-tested: Hard Wax release search, track found in a release's tracklist with `appears_on`, a split release's track artist, another version (a remix) kept out with a version discrepancy, query URL with `?focus=`, earlier-pass link, sections without catalogue sections, no label or text, track missing from the page, no match, challenge → `blocked`, invalid feed and pages without a release; Soundohm release search with the full text, track query `not_found`, another version (live album) kept out, query URL, earlier-pass link, facts without JSON-LD, empty description, challenge → `blocked`, pages without a release; merge: one press text from two shops once with both sources, a shortened copy, a copy with an extra line, a shop copy of a label text, short and review texts kept apart.
- Live-verified (`--no-cache`): `--album "Burial - Untrue" --sources core,shops` 31 s (Hard Wax and Soundohm shop texts and links; Soundohm's "Electronic" merged with five sources; Soundohm's year 2008 is a `date` discrepancy); `--track "Burial - Archangel" --sources core,hardwax,soundohm` 36 s (Hard Wax text and `appears_on` Untrue; Soundohm `not_found`). Five v1 check records with `core,hardwax,soundohm`: Huerco S. 27 s (Hard Wax "Superb Ambient / Electronica album - 2025 repress"); Paranoid Android 41 s, ESTADO DE BIENESTAR 23 s, Кино 39 s, Missing (Todd Terry Remix) 48 s — both shops `not_found`, as neither carries them. Bandcamp timed out or failed in some of these runs and answered on a repeat; Bandcamp is unchanged.
- Not live-verified: deduplication (Kali Malone and Caterina Barbieri had no shop text repeated by another source).

Observed, not changed: when no candidate is accepted, `merge` takes the reference version from accepted candidates only, so a query that names a version ("Archangel (Extended Mix)") against a found original gets an `other_version` relation but no `version` discrepancy.

Remains for Stage 12: Juno and Phonica from pages the user saves in a browser (search for "Burial Untrue" and the Untrue product page; search for "Everything but the Girl Missing" and one product page), then their adapters, URL rules, docs, and the user's live checks.

### 2026-11-13 — Stage 12 evidence (Juno)

Pages: the user saved seven Firefox view-source pages (searches for "Burial Untrue" and "Everything but the Girl Missing"; products 285827-01, 1105467-01, 1105468-01, 1188113-01, 733799-01); six became fixtures in `tests/fixtures/juno/pages/` (9–115 KB). Phonica's site is `phonicarecords.com`; it answers a Sucuri JS challenge (307, `server: Sucuri/Cloudproxy`).

Changed: package `juno` (adapter | parse, R8 contract, R4 row), group `shops`, opt-in, rate 0.5; `track_on_release` in `_base.py` (Hard Wax uses it too); Juno and Phonica URL rules (`/products/<slug>/<id>-<n>`, `/product/<slug>/<id>`); `phonicarecords.com` service; Sucuri challenge marker; `scripts/saved_pages.py` replaces `scripts/beatport_pages.py`; settings, `.env.example`, recorder host, docs, README.

Commands and outcomes:

- `uv run python scripts/saved_pages.py --shop beatport …` on the six saved Beatport pages: fixtures unchanged (`git status` clean for `tests/fixtures/beatport`).
- `uv run poe check`: format, lint, 27 import contracts kept, mypy strict clean, 831 passed, 99.07% branch coverage.
- `uv run --group docs properdocs build --strict`: built without warnings.
- Mock-tested (saved pages): release search with review, label, catalog number, date and genre; a track found in a result's tracklist with `appears_on`; "Missing (Todd Terry Remix)" matches Juno's "Todd Terry club mix" (a club mix is not a cut) and is accepted by `merge` as the remix, with genre and three Juno tags; the original "Missing" is found on Amplified Heart; "unknown label" and a missing date are left out; query URL, earlier-pass link, page without canonical link; track missing from the page; no match; challenge → `blocked`; page without a product; tracklist entries with mix names and compilation artists; the Sucuri marker.
- Live: one run by the agent, `deadwax --album "Burial - Untrue" --sources core,juno --no-cache`, was started without `DEADWAX_HTTP__ESCALATION=none`, against the plan for this stage. The run journal (`20261113T155818Z-92468f`) shows Juno's search answering httpx with a Cloudflare challenge and the escalation ladder's impersonation step reading the search and the product page; Juno contributed the review, "Deep Dubstep" and the link. No further agent runs against Juno were made. Live checks of tracks and other records remain with the user.

Remains for Stage 12: Phonica from saved pages (the site's search for "Burial Truant", `/product/burial-truant-rough-sleeper-hyperdub/111124`, `/product/huercos-colonial-patterns-lp-software/116278`).

### 2026-11-13 — Stage 12 evidence (Phonica)

Pages: the user saved two Firefox view-source product pages (111124 Burial "Truant / Rough Sleeper", 116278 Huerco S. "Colonial Patterns LP"); both became fixtures in `tests/fixtures/phonica/pages/` (82–89 KB). The search page was not saved. The site's search is `/search/<words>` (from a link in the page); its results are assumed to use the product cards seen on product pages (`.archive-products .product-place-holder` with `.archive-artist`, `.archive-title`, `.archive-playlist`), which is not verified.

Changed: package `phonica` (adapter | parse, R8 contract, R4 row), `SearchPageAdapter`, group `shops`, opt-in, rate 0.5, added after Juno in `ADAPTERS`; `scripts/saved_pages.py` keeps `#page-single` for Phonica (the page has no `main`); settings, `.env.example`, recorder host, `docs/sources.md`, `docs/architecture.md`, API reference index, README table and tree.

Extracted: staff description as a `shop` text (paragraphs from `<p>` or double `<br>`), genre sections as `genre` tags, label, `og:url` as the page URL, "customers who bought this also bought" as `similar` relations (empty template cards skipped), the product link; for a track, `appears_on` from the page's playlist. A trailing format ("LP", "2LP", "2 x LP", "CD") is removed from titles; "EP" is kept. Product pages carry no date and no catalog number.

Commands and outcomes:

- `uv run python scripts/saved_pages.py --shop phonica … --name product_111124 --name product_116278`: two fixtures written.
- `uv run poe check`: format, lint, 28 import contracts kept, mypy strict clean, 847 passed, 99.05% branch coverage.
- `uv run --group docs properdocs build --strict`: built without warnings.
- Mock-tested: release by search (synthetic result cards) with text, three genres, label and three also-bought releases; a track found through a card's track list with `appears_on`; another version (a remix) kept out with a version discrepancy; query URL with paragraphs and a format in the title; earlier-pass link; a bare page; track missing from the page; no match; Sucuri challenge → `blocked`; page without a product; title formats.
- Not live-verified: no live run was made.

Remains for Stage 12: the user saves `https://www.phonicarecords.com/search/burial%20truant`; the agent checks the search parser against it and turns it into a fixture. Then the user's live checks (Phonica needs the escalation ladder for Sucuri), and the stage is marked Done.

### 2026-11-13 — Stage 12 evidence (Phonica search)

Observed (user's browser, HAR and screenshots): the search page is filled by `POST /api/product/json_category_search/<words>/0` with the form `id=0&href=/search/<words>/&offset=0`; the answer is JSON (served as text/html) with products under keys "0".."17" (`artist`, `album`, `slug`, `product_playlist`, shortened names end in "..."), or `"not_found": 1`. The search finds a phrase only within one field: "truant", "burial", "truant / rough sleeper" find results; "burial truant", "truant rough sleeper" find nothing. A typed `/search/<words>` URL is not decoded by the site. The product-card assumption of the previous entry was wrong and is replaced.

Changed: `SearchPageAdapter.search` is a new overridable step (the default GET search moved there from `_page_url`); Phonica overrides it with POST requests, by title (version and anything after " / " removed) and then by artist, reading the first page only; `phonica.models` (search API products; R8 contract now adapter | parse | models); search fixtures `search_truant.json` (the HAR answer, trimmed fields) and `search_not_found.json`; docs and the evidence above updated.

Commands and outcomes:

- `uv run poe check`: format, lint, 28 import contracts kept, mypy strict clean, 854 passed, 99.08% branch coverage.
- `uv run --group docs properdocs build --strict`: built without warnings.
- Mock-tested: release search by title picks the first matching edition (the CD before the vinyl in the saved answer); a track found by the artist search after the title search finds nothing; another version kept out; no match after both searches; a self-titled record searched once; an answer without JSON; the request method and form.
- Not live-verified: no agent request was sent to Phonica.

### 2026-11-13 — Stage 12: Phonica moved out, stage closed

Live (user, `--sources core,phonica --no-cache`, escalation on): runs `20261113T182921Z-ee4243` (album "Burial - Truant / Rough Sleeper") and `20261113T182947Z-405725` (track "Burial - Rough Sleeper") — Phonica `failed: HTTP 403` on the first search request, a 288-byte page that is not a challenge, so the ladder did not escalate. The user's curl: the search POST answers Apache "403 Forbidden" with and without `Origin`/`Referer`; a plain GET of a product page answers Sucuri 307 (1359 bytes).

Decision (user): Phonica leaves Stage 12 and joins the unscheduled blocking item. Removed: package `phonica`, its tests and fixtures, registry entry, settings, `.env.example` lines, R4 row and R8 contract, recorder host, docs and README rows (files restored to their state before `9af10f2`). Kept: the Phonica URL rule and service name (they predate the adapter), the Sucuri challenge marker, the `#page-single` rule in `scripts/saved_pages.py`, and the new overridable `SearchPageAdapter.search` step (default behaviour unchanged). The adapter is preserved in commit `9af10f2` and `plans/phonica-search.patch`.

Stage 12 closed: Hard Wax, Soundohm, Juno, and shop-text deduplication meet the acceptance; Juno's live verification is the single agent run recorded above, Hard Wax and Soundohm were live-verified, deduplication is mock-tested only.

**Current task:** Stage 14 complete. **Next action:** Stage 15, reviews I.

### 2026-11-13 — Stage 13 access check (in progress)

The working tree was clean before the check. Requests for the Boomkat `Untrue`, Norman Records `Untrue`, Bleep `Untrue`, and Forced Exposure home pages returned HTTP 403 from this environment. Norman Records returned a Cloudflare "Just a moment" page both with plain curl and with the installed curl_cffi Chrome impersonation. Removing proxy environment variables did not change its response. The search index shows product pages for Boomkat, Norman Records, Bleep, and Forced Exposure, but it does not expose their HTML structure or verify that deadwax can fetch them. No adapter or parser was added; Stage 13 remains open. Saved search and product pages, or working live access, are needed to build verified extraction fixtures.

Playwright Chromium follow-up: Boomkat and Norman Records product URLs still returned 403 Cloudflare pages; a Forced Exposure product returned 403. Bleep's `Untrue` product returned HTTP 202 and, after eight seconds, rendered its actual page (artist, title, date, description, tracklist). Its search form is `GET /search/query?q=…`: `Burial Untrue` returned no results, while `Untrue` returned the release. The rendered product and search HTML were saved temporarily at `/tmp/bleep_untrue.html` and `/tmp/bleep_search_untrue.html` for parser research; they are not repository fixtures. No adapter or parser was added; the other three sources still need readable pages.

### 2026-11-14 — Stage 13 evidence

The system Chrome 157 returned `net::ERR_INVALID_HANDLE` for an external page even when launched directly without Nodriver; Chrome for Testing 156 loaded it. Nodriver with an explicitly selected Chrome for Testing executable and `sandbox=False` loaded external pages. Nodriver now treats Chrome's network error page as `TransportError`, avoiding a false HTTP 200. Both settings are opt-in; the default sandbox remains enabled.

With the working browser, Nodriver still received Cloudflare 403 for Boomkat and Norman Records products. Per the user's decision, both sources are deferred. Forced Exposure and Bleep use Patchright first. Their product pages returned real HTML through Patchright, and their search and product pages were saved as fixtures (request-verification tokens removed).

Implemented: opt-in Forced Exposure and Bleep adapters using `SearchPageAdapter`, source configuration and URL recognition, README and source documentation. Forced Exposure extracts a release's label copy, genre, label, catalog number, date, and recommended releases. Bleep extracts editorial copy, genre sections, label, catalog number, date, and a track's `appears_on` relation when listed. Search results pass through the matching gate.

Verification: `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (836 tests, 98.41% branch coverage; format, lint, 30 import contracts, and strict mypy passed). `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. Saved-page tests cover search and extraction; offline checks cover absent pages, another version, and the Chrome error. Live library lookups with Patchright and no cache: Bleep's *Burial — Untrue* returned one text and one genre without errors; Forced Exposure's *VA — Hyperdub 5.4 EP* returned one text, one genre, ten related releases without errors. Of five check records, Forced Exposure returned a text for Huerco S.; both stores returned `not_found` for the other four, and Bleep returned `not_found` for Huerco S. A live Nodriver request using system Chrome now raised `TransportError` for its Chrome error page.

### 2026-11-14 — Stage 14: Genius

Decision (user): store full song lyrics when Genius serves them. Implemented a token-authenticated Genius adapter in the enrichment pass, added it to the default set, and represented lyrics as a `lyrics` text with `work` scope. API description, annotations, writer and producer credits, song relationships and the song link remain available when the separate HTML fetch fails. Missing token yields `skipped`. Added Genius settings, credential instructions, source and output documentation, and import contracts.

Verification: `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (840 tests, 98.17% branch coverage; format, lint, import contracts, strict mypy). Mock transport tests cover API extraction, full lyrics with line breaks, no matching song, absent lyrics, and blocked HTML. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed after documentation edits. No live Genius lookup was possible: neither the environment nor the local `.env` contains a Genius token. Therefore API payload fields and live HTML behaviour remain unverified; no live runs on the five check records or a Genius-strong record were performed.

### 2026-11-14 — Stage 14 live verification and closure

The user added `DEADWAX_GENIUS__TOKEN` to the untracked `.env`. Live lookups with caching disabled and the default HTML escalation ladder confirmed Genius API fields and full lyrics: *Kanye West — Stronger* returned 20 annotations, 8 credits, 93 relations including samples and interpolations, and lyrics; *Radiohead — Paranoid Android* returned 13 annotations, 9 credits, relations, and lyrics; *Everything but the Girl — Missing (Todd Terry Remix)* returned the remix with lyrics, 5 credits, and a `remix_of` relation. Both album check records returned no Genius facts, as intended for a song-only adapter. *Кино — Группа крови* returned `not_found` because the search had no exact match. A plain HTTP fetch met Cloudflare; the configured escalation ladder retrieved the HTML page. No token or lyric body was recorded.

Added the Genius token to the opt-in integration configuration and a live invariant test. The targeted live test passed (one test, 11.68 s). `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (840 offline tests, 98.17% branch coverage; format, lint, import contracts, strict mypy). The full `poe test-live` suite was not run; the live check was limited to the new source and the five acceptance records.

## Resume instructions

### 2026-11-14 — Stage 15 in progress

The worktree was clean at the start. Added opt-in AllMusic and Album of the Year adapters, review links as a separate sourced field on partials, dossiers, and lookup context, MusicBrainz review URL relations, user-score metrics, and score-to-review deduplication. Updated settings, URL recognition, CLI and Markdown rendering, README and source documentation. Synthetic page tests cover the modeled extraction paths, version rejection and review-link isolation; they do not verify either site's real markup.

Direct public-page requests from this environment returned Cloudflare HTTP 403 for AllMusic's *OK Computer* and Album of the Year's *OK Computer*. A live lookup of that album with both new sources and `--no-cache` returned no identity: AllMusic timed out after 30 seconds; Album of the Year's search failed because Chrome could not load it. Saved search and product pages have been requested from the user. Live source facts and real-page parser behavior remain unverified. Do not mark Stage 15 Done until real saved pages are checked and the stage's live-run acceptance is recorded.

`UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed: format, lint, 30 import contracts, strict mypy, 843 tests, and 97.61% branch coverage. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. `git diff --check` passed. The five check-record live runs were not performed because both source pages were inaccessible in the strong album check.

Nodriver-only follow-up (2026-11-14, user request): used Chrome for Testing 156, `nodriver_sandbox=false`, `html_transports=["nodriver"]`, `http.escalation=["nodriver"]`, and `--no-cache`. The *OK Computer* search was blocked by a Cloudflare challenge on AllMusic (run `20261114T145611Z-a66b8c`, one Nodriver attempt, 4.6 s) and Album of the Year (run `20261114T145626Z-489db3`, one Nodriver attempt, 3.6 s). Neither site yielded a page or facts. The HTTP status of Nodriver's response was not recorded because the challenge is reported as `BlockedError`.

Browser transport follow-up (2026-11-14, user request): added an explicit Patchright Chrome mode with a temporary profile and no user-agent, language-header, or viewport overrides. Patchright and Nodriver now poll only while a challenge or required page marker remains, up to `http.browser_challenge_wait` seconds; ready pages return immediately. Required markers pass to browsers without changing cache keys. Added configuration examples and offline tests for Chrome profile cleanup, delayed content, and wait expiry. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (848 tests, 97.62% branch coverage, format, lint, import contracts, strict mypy); the strict docs build passed. Live comparisons were not run because this environment's access to the protected pages is blocked; the source facts and real-page parsing remain unverified. Stage 15 stays in progress.

Persistent browser profile follow-up (2026-11-14, user request): added optional, separate profile paths for Patchright and Nodriver, retained after a lookup. Matching paths are rejected, and the blocked-cache policy changes when profile settings change. Documented an explicit single-transport, visible-browser workflow with enough time for a manual challenge. Offline tests cover profile arguments and path validation. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (851 tests, 97.63% branch coverage); the strict docs build passed. A local real-browser smoke attempt could not launch either installed Chrome through the two transports in this sandbox and returned configuration errors; no profile-based site access was verified. Stage 15 remains in progress.

Global Patchright profile follow-up (2026-11-14, user request): configured one dedicated profile in the user's ignored `.env` for every current and future HTML source that uses Patchright, with headless Chrome by default. Added per-lookup serialization and browser closure after each persistent-profile request so concurrent adapters do not launch Chrome on the same profile. An offline concurrency test passed. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (852 tests, 97.63% branch coverage), and the strict docs build passed. A real Chrome launch initialized the profile and created `Local State` when run with the required filesystem permission. Site challenges were not exercised and cookies for sites not yet visited are absent. Stage 15 remains in progress.

Lookup browser flags follow-up (2026-11-14, user request): added `--headless`, `--headed`, and `--html-transport` to `lookup`. The transport flag sets an exact ordered list for every HTML source in one lookup and permits its optional transports even when the saved global allowlist is narrower; it does not change API requests or saved settings. CLI tests cover precedence, one-run isolation, credential preservation, and invalid arguments. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (858 tests, 97.65% branch coverage); the strict docs build and CLI help check passed. No protected-site live run was performed. Stage 15 remains in progress.

Patchright navigation repair (2026-11-14, user screenshot and live runs): the Bleep run journals showed system Chrome 157 failing `Page.goto` with `net::ERR_INVALID_HANDLE`, leaving `about:blank`; a driver-close error then masked the original failure. A separate Chrome for Testing 156 profile was created and selected in the user's ignored `.env` with `patchright_channel=chromium`, preserving the old profile. Patchright now suppresses driver-close errors during cleanup and detects Bleep's AWS WAF 202 page as a challenge, allowing the configured challenge wait. Live Bleep lookups of *Burial — Untrue* with `--html-transport browser --no-cache` succeeded in headless and headed modes, each returning a sourced text with no errors. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (861 tests, 97.65% branch coverage), and the strict docs build passed. Stage 15 remains in progress because AllMusic and Album of the Year still need real-page verification.

Deferred-shop profile probe (2026-11-14, user request): used the dedicated Patchright Chrome for Testing 156 profile, then a separate Nodriver profile with the same browser executable. These were direct browser transport probes, not adapter lookups; no adapter or fixture was added. Patchright returned real Phonica *Truant / Rough Sleeper* product HTML (200) in headed and headless modes. Its search-page GET returned a generic page, so the site's own POST API was tested with title `truant` and artist `burial` separately, using its form fields and browser cookies: both returned result JSON (200) in headed mode; artist `burial` also returned result JSON in headless mode. The first result pages did not establish that the exact *Truant / Rough Sleeper* product is present among the search hits. Boomkat *Untrue* product and `Burial Untrue` search returned real HTML (200) in headed Patchright and Nodriver; the Boomkat search HTML contained the target product. Both transports received Cloudflare challenge pages in headless mode (Patchright 403; Nodriver reported 200 for challenge HTML). Norman Records *Untrue* product returned real HTML (200) in headed Nodriver; headed Patchright hit a navigation/content race, while both transports got challenge HTML in headless mode. Norman search was not verified: `/search?q=Burial+Untrue` redirected or challenged, and `/cloudsearch/index.php?q=Burial+Untrue` was intermittently challenged or returned a page without confirmed product hits. The isolated Nodriver profile is not selected in `.env`. Stage 15 remains in progress; these probes do not complete its AllMusic and Album of the Year acceptance.

Deferred-shop implementation follow-up (2026-11-14, user request): restored Phonica's archived product and JSON-search parser, added a same-origin Patchright POST that uses the persistent profile's cookies, and added opt-in Boomkat and Norman Records adapters. Phonica defaults to headless Patchright; Boomkat defaults to headed Patchright; Norman Records defaults to headed Nodriver with its own profile and browser path selected in the ignored `.env`. Per-lookup browser flags override these defaults. Boomkat searches and reads product editorial copy and genres. Norman Records reads only a direct or context product URL, with identity and genres; its text search and staff-review extraction remain unverified. The *Untrue* page has customer reviews but no staff review, so no text is fabricated. Sanitized search and product fixtures were made from readable live pages. A live no-cache Phonica lookup of *Burial — Truant / Rough Sleeper* succeeded in headless mode with one shop text, four tags, and no errors. Boomkat and Norman Records live CLI lookups returned Cloudflare challenges in headed mode, including one retry with a 60-second challenge wait, although earlier direct transport probes and fixture parsing succeeded. This access instability limits live acceptance for those two sources. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (889 tests, 97.45% branch coverage, formatting, lint, import contracts, strict mypy), the strict documentation build passed, and `git diff --check` passed. Stage 15 remains in progress for its separate review-source acceptance.

### 2026-11-15 — Stage 15 AllMusic real-page verification

The working tree was clean at the start. The dedicated Patchright profile opened AllMusic's *OK Computer* album search and product page with HTTP 200. The real search uses `div.album` rows, and the product uses `.albumTitleText`, `#albumArtists`, `#review`, `ratingAllmusic9`, mood and theme columns, and a credits table. Updated the parser for these structures and kept its earlier selectors for older pages. A short, sanitized fixture preserves the verified structure without the full review or browser data. A live no-cache `--sources allmusic --headed --html-transport browser` lookup of *Radiohead — OK Computer* returned identity, one review with 4.5/5 and Stephen Thomas Erlewine, 26 tags, eight credits, and no errors.

A combined live Wikipedia and AllMusic lookup had no source errors. Wikipedia listed two distinct 5/5 AllMusic ratings, one under retrospective reviews and one under Collector's Edition ratings; the current AllMusic album page rated the album 4.5/5. The merge kept these distinct rather than giving one rating conflicting provenance. Album of the Year's search and direct *OK Computer* page still returned Cloudflare challenge HTML through headed Patchright; its search also returned a challenge through headed Nodriver. No real AOTY HTML or extraction fixture was obtained. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (890 tests, 97.60% branch coverage, formatting, lint, import contracts, strict mypy); the strict documentation build and `git diff --check` passed. Stage 15 remains in progress.

### 2026-11-15 — Stage 15 Album of the Year real-page parser verification

The user manually cleared the Album of the Year challenge in a headed Patchright browser using the dedicated persistent profile. Direct browser requests then returned HTTP 200 for the *OK Computer* search (27 KB) and album page (96 KB). The search parser already found the exact album. The album parser incorrectly took its artist from a sidebar and missed all critic scores, user score, genres, and review links. Updated its selectors against the real page and added sanitized search and album fixtures. Fixture tests now extract Radiohead, 16 critic scores, a 93/100 user score, genres, and publication review links. The existing score-merge test covers equal Wikipedia and AllMusic ratings; the distinct live *OK Computer* ratings remain separate.

Live limitation: a normal no-cache `deadwax lookup 'Radiohead - OK Computer' --album --sources albumoftheyear --headed --html-transport browser` returned `blocked` at the search URL on a fresh browser request, despite the successful direct page captures. The initial CLI attempt returned `not_found` before the user cleared the challenge. Thus AOTY extraction is real-page fixture-verified and its pages were fetched live, but a complete live adapter lookup and the five check-record runs remain unverified. Stage 15 stays In progress.

Verification: `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (891 tests, 97.74% branch coverage; format, lint, 33 import contracts, strict mypy). `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. The five check-record runs were skipped because the strong-record CLI request remained blocked.

### 2026-11-15 — Stage 15 live acceptance retry

The worktree was clean at the start. A no-cache, headed Patchright CLI lookup of *Radiohead — OK Computer* with only Album of the Year returned `blocked` on `https://www.albumoftheyear.org/search/?q=Radiohead+OK+Computer`: Cloudflare challenge after one browser transport. The first attempt inside the sandbox could not access Patchright's installed Chromium; the retry with browser/profile access launched successfully and reached the site. This is an access failure, not a parser result.

Ran the five v1 manual-check records plus *OK Computer* with `--sources allmusic,albumoftheyear --headed --html-transport browser --no-cache --format json`. All six lookups reported `blocked` at each source's search URL, with no identity or extracted facts. The previous AllMusic live success and both real-page fixture tests remain valid, but neither source passed this session's end-to-end live checks. No adapter defect was established, so no source code or fixture was changed. Stage 15 remains In progress; a complete Album of the Year live lookup and the five-record acceptance gate are still pending. No Stage 16 work started.

`UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (891 tests, 97.74% branch coverage; format, lint, 33 import contracts, strict mypy). `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run --group docs properdocs build --strict` passed. The full `poe test-live` suite was not run because this retry targeted Stage 15's six records and the browser search was blocked.

### 2026-11-15 — Stage 15 closure after headed browser verification

The user confirmed that headed Chrome displayed the normal Album of the Year search results without a challenge. The request still reported `blocked`: a normal HTTP 200 page loaded Cloudflare's `/cdn-cgi/challenge-platform/scripts/precursor/` script, which the challenge detector mistook for an active interstitial. A direct browser probe confirmed the page title, status, and marker. The detector now ignores that precursor script while retaining detection of actual challenge pages; an offline regression test covers the normal page.

The no-cache, headed Patchright CLI lookup of *Radiohead — OK Computer* then completed through search and album page: 16 critic scores, a 93/100 user score, four genre tags, 16 publication review links, and no errors. The five v1 check records were run with `--sources allmusic,albumoftheyear --headed --html-transport browser --no-cache --timeout 180 --format json` and `DEADWAX_HTTP__BROWSER_CHALLENGE_WAIT=120`. *Huerco S. — For Those of You Who Have Never (And Also Those Who Have)* returned eight texts, 28 tags, one credit, one user-score metric, eight review links, and no errors. The other four records returned `not_found` from both sources, with no blocked or failed errors; neither adapter supplied facts for a different version. A combined live *OK Computer* lookup with Wikipedia, AllMusic, and Album of the Year returned no errors. Wikipedia's two 5/5 AllMusic scores, AllMusic's current 4.5/5 score, and Album of the Year's 100/100 AllMusic score remained distinct; the equal-score merge is covered by the offline test.

`UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (892 tests, 97.74% branch coverage; format, lint, 33 import contracts, strict mypy). The full `poe test-live` suite was not run; live verification covered the Stage 15 sources and five acceptance records. Stage 15 is Done. No Stage 16 work started.


### 2026-11-15 — Stage 16 in progress

The user chose full available review text and Pitchfork, The Quietus, and The Wire for the press adapter. Added an opt-in `pressreviews` adapter in the links pass, with per-site HTML selectors, record matching, configuration, documentation, and synthetic extraction tests. It consumes review links from earlier passes. No real press page was captured, so those selectors and end-to-end extraction are not live-verified. The Resident Advisor GraphQL adapter, biographies, and DJ charts remain unimplemented. A sandboxed request could not resolve `ra.co`; an unsandboxed request to a public review returned HTTP 403, so the GraphQL operation and response shape could not be captured. The five-record and strong-record live acceptance runs were not performed.

`UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (896 tests, 97.38% branch coverage; format, lint, 33 import contracts, strict mypy). The strict documentation build and `git diff --check` passed. Stage 16 remains In progress until all deliverables are implemented and accepted.

### 2026-11-15 — Stage 16 headed-browser follow-up

The dedicated headed Patchright profile opened RA's *Burial — Untrue* review (HTTP 200). Its Next.js Apollo state contains `Review:4920`; the browser sent six GraphQL operations. A directly tested `review(id)` GraphQL query returned title, type, full content, author, artist biography, and label blurb. Added the opt-in `residentadvisor` adapter for linked review URLs. A live adapter lookup of *Burial — Untrue* through the library transport returned the matching album, a 2,760-character review, and a label biography. RA's official site-redesign FAQ says DJ charts are no longer supported; the current `/charts` page returned 404, so chart relations are dropped rather than fabricated.

Headed Chrome also fetched Pitchfork's *Amnesiac* and The Quietus's *Tunes, 2011 to 2019* review pages (both HTTP 200). The first press parser failed on both; updated the site rules from their live markup. The parser now returns 12,819 and 17,289 characters respectively on those pages, with matching artist and title. Added small markup tests. The Wire has not been checked on a real review page, and the five-record acceptance runs remain pending. Stage 16 remains In progress.

`UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (900 tests, 96.89% branch coverage; format, lint, 33 import contracts, strict mypy). The strict documentation build and `git diff --check` passed. The full live suite was not run; the live probes above targeted the new sources.

### 2026-11-15 — Stage 16 completion

The Wire's *Hen Ogledd — Discombobulated* review opened in headed Chrome (HTTP 200). Its page names the artist and album inside the first review-body paragraph, not the headline. The site rule now reads that identity, extracts 4,418 characters of review text and author Abi Bliss, and excludes the magazine issue notice. A small markup test covers this shape. Pitchfork's live *Amnesiac* page stores its 9/10 score in the current review header of `__PRELOADED_STATE__`; the parser reads that field, not scores of recommended reviews, and a test covers it.

RA's public GraphQL schema exposed `search(searchTerm, indices: [REVIEW])`. Browser-verified searches for *Burial — Untrue* and *Huerco S. — For Those of You Who Have Never (And Also Those Who Have)* returned exact review IDs among other results. The RA adapter now searches when context has no review link, matches the result before fetching it, and retains the earlier linked-review path. Mock tests cover search, another version rejected, biographies, blocked responses, and not found. Live library searches returned a 2,760-character review and a label biography for *Untrue*, and a 1,965-character review and a label biography for *For Those...*. Artist biography extraction remains mock-tested because those two reviews supplied none.

The five v1 check records were run live and without cache. With MusicBrainz, Album of the Year, press reviews, and RA selected, *Huerco S.* returned a 10,594-character Pitchfork review; the other four had no linked review on the supported press sites and returned `not_found` rather than a wrong record. RA search alone returned the *Huerco S.* review and `not_found` for the other four; no failed or blocked errors occurred. *Burial — Untrue* was the extra strong record: the combined live lookup returned Pitchfork and RA reviews. A second combined run of *Huerco S.* and *Untrue* returned both publications' full reviews with no errors. Direct live page parsing was verified for all three press sites, while full lookup coverage for The Quietus and The Wire remains limited by absence of their links in those check records.

`UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (904 tests, 97.29% branch coverage; format, lint, 33 import contracts, strict mypy). The strict documentation build and `git diff --check` passed. The full `poe test-live` suite was not run; live verification targeted the Stage 16 sources and acceptance records. Stage 16 is Done. RA DJ charts were dropped because [RA says the redesigned site no longer supports them](https://ra.co/news/74703).

> Read `AGENTS.md`, `docs/architecture.md`, and `DEADWAX_PLAN.md`. Inspect the branch, worktree, stage table, and latest evidence. Implement the first incomplete stage only, preserving accepted and standing decisions and import rules. Run the stage checks, append dated evidence, update the status only when acceptance passes, report an English commit message, stop at the stage boundary, and do not create commits.

### 2026-11-15 — Stage 17 in progress

The worktree was clean at the start. Added opt-in NTS and WFMU adapters, `co_played` relations, and a `context_url` on tags. Mocked lookup tests verify NTS episode, neighbour and genre extraction and WFMU playlist comments. Source registration, CLI settings, documentation, and import contracts were updated. `UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (906 tests, 97.07% branch coverage), the strict docs build passed, and `git diff --check` passed.

Live verification is incomplete: the public NTS `/api/v2/search` returned HTTP 200 with an empty `results` list for Burial, Archangel, and a suggested popular term. WFMU's advanced playlist search returned HTTP 200 with “Sorry, you cannot run searches at this time.” No end-to-end live lookup on the five check records or a strong record succeeded. The recorded payloads are synthetic, so current extraction paths remain unverified against live result and playlist markup. Stage 17 remains in progress; do not begin Stage 18.

### 2026-11-15 — Stage 17 headed-browser verification

The dedicated visible Patchright profile opened NTS `/find?q=burial%20archangel` and its JSON search endpoint without a challenge. Both said that no episodes or tracks were found. It also opened WFMU's advanced search form, but a form submission for *Radiohead — Paranoid Android* still returned “Sorry, you cannot run searches at this time.” The browser therefore does not clear either search blocker.

Direct known pages were available in the same browser. NTS's *Jumpin Jack Frost Presents: 30 years of Burial* episode returned an episode JSON document with `embeds.tracklist.results`, `genres[].value`, and an ISO `broadcast` timestamp. WFMU's *Wake with Clay Pigeon* playlist (2026-07-21) returned a real *Paranoid Android* row: the track title is in `.col_song_title font`, its DJ note is in `.col_comments font`, and the last table cell holds the play time. Corrected both parsers and updated the mocked tests to represent these verified structures. Full search-to-episode lookup remains unverified because both public searches returned no usable results. Stage 17 remains in progress.

### 2026-11-15 — Stage 17 completion

NTS's current site uses `/api/v2/search` with `version=2` and `types[]=track`; the earlier `type=track` request returned empty results. The v2 hits include `title`, `artists`, and `article.path`. The adapter now filters hits through the matching gate before reading up to ten matching episode tracklists. WFMU's basic and advanced forms still say searches cannot run, but its artist browser works: its initial index identifies the artist, and the artist's play listing gives titles, dates, and playlist links. The adapter now filters that listing before reading up to ten recent matching playlists and dates broadcasts so separate days do not merge. An HTTP-client POST required the action in explicit `params` to preserve it; a live lookup found that bug and confirmed the repair. No user-supplied playlist URL feature was added.

Mock-tested: NTS v2 search, a rejected live version, episode genres and neighbouring tracks; WFMU artist index, play listing, a rejected live version, playlist comments and dates; both sources' blocked and not-found paths. Live no-cache lookups with 2 requests/s and a 90-second adapter timeout: *Paranoid Android* returned 2 NTS and 10 WFMU broadcasts without errors; both album check records correctly returned `not_found` without requesting song searches; *Кино — Группа крови* returned an NTS broadcast and WFMU `not_found`; *Missing (Todd Terry Remix)* returned 4 WFMU broadcasts and NTS `not_found`. Extra strong record *Burial — Archangel* returned 10 NTS and 6 WFMU broadcasts. A second no-cache *Archangel* lookup with the normal rate and 30-second timeout completed in 22.1 seconds with 16 broadcasts, 20 neighbouring-track relations, 30 context tags, and no errors. The full `poe test-live` suite was not run; live verification targeted Stage 17's five check records and strong record.

`UV_CACHE_DIR=/private/tmp/deadwax-uv-cache uv run poe check` passed (909 tests, 97.04% branch coverage; format, lint, 33 import contracts, strict mypy). The strict docs build and `git diff --check` passed. Stage 17 is Done. No Stage 18 work started.

Distinguish planned, implemented, mock-tested, and live-verified behaviour in every handoff.
