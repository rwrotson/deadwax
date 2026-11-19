# deadwax v2: implementation plan and handoff journal

## Status and handoff

This is the active specification and multi-session handoff for deadwax. deadwax collects, for one track or album, what open sources know about that exact recording, with four goals: (1) texts describing its sound, (2) relations for further searches, (3) confirmation of the exact recording and version with visible discrepancies, (4) streaming links. v1 (eight sources) is complete; its plan, stage evidence, and full decision log are archived in [`plans/v1.md`](plans/v1.md). Closed v2 stages (8–17, 19, R-1–R-5), their evidence, and the v2 decision log are archived in [`plans/v2.md`](plans/v2.md).

- **Status:** v1 complete and committed. v2 source scope recorded (`## v2 sources`); v2 stages 8–20 defined; Stages 8–17 and 19 done, Stage 18 deferred until RYM is accessible (Boomkat and Norman Records remain access-limited). Structural refactoring stages R-1–R-6 (2026-11-19) run before Stage 20; R-1–R-6 done. Stages M-1–M-3 (2026-11-20, requests and data for the mixhound consumer) run before Stage 20; M-1–M-3 done. Stage 20 is next.
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
| Requests | Applications ask for facets (`Capability`), not sources; configuration decides which sources may run. One `Deadwax` client shares cache, rate limiters, and browsers across lookups; adapters are built per lookup (2026-11-20, `docs/requests.md`). |
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
| M-1 | Done | Requests by facets, the long-lived `Deadwax` client. |
| M-2 | Done | Leads: LB Radio, Last.fm similar artists for tracks, MusicBrainz associated artists. |
| M-3 | Done | Bandcamp stream previews, ISRC in queries. |
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

### Stages M-1–M-3: requests and data for mixhound

Agreed with the user on 2026-11-20. mixhound, an application that finds recordings similar to reference tracks, takes all its track data from deadwax: one lookup per track that names the data it needs, through one client for the whole process. Breaking changes carry `!`. Each stage passes `uv run poe check` and the strict docs build and ends with evidence and a commit suggestion. Design: `docs/requests.md`.

- **M-1 (requests and client).**
  - Add `Request(query, facets, tags_per_source, relations)` and `RelationLimit(kind, target, per_source)` in `core/request.py`, and `Capability.PREVIEWS` on iTunes, Spotify, Deezer, and Bandcamp.
  - Select adapters by facet (the identity pass always runs), add `LookupContext.wants()`, and trim the dossier to the request (`core/select.py`).
  - Add `Deadwax` (`sources/client.py`): cache, rate limiters, and browsers live as long as the client; adapters are built per lookup. `lookup()` becomes a one-call wrapper accepting a `Query` or a `Request`.
  - Last.fm, ListenBrainz, MusicBrainz, and Bandcamp skip requests for facets that were not asked for.
  - Add the CLI `--facet` option.
- **M-2 (leads).**
  - ListenBrainz LB Radio (`/1/lb-radio/artist/{mbid}`, `mode=easy`, 8 artists × 2 recordings, titles resolved through `/1/metadata/recording/`) → new `RelationKind.SIMILAR_ARTIST_RECORDING`.
  - Last.fm `artist.getSimilar` also for tracks.
  - MusicBrainz artist relations: `member of band` stays `member`/`project`; is person, collaboration, supporting / vocal / instrumental supporting musician, subgroup, founder, artist rename, tribute, and producer become new `RelationKind.ASSOCIATED` with the MusicBrainz type in `note`.
- **M-3 (previews and ISRC).**
  - The Bandcamp `mp3-128` stream URL from `data-tralbum` becomes the track link's `preview_url`; nothing is downloaded.
  - `IdKind.ISRC` is accepted in `Query.ids` and used by the MusicBrainz ISRC lookup and the Spotify ISRC search; CLI `--isrc`.

**Suggested messages:** `feat!: request dossiers by facets through a long-lived Deadwax client`; `feat(sources)!: add LB Radio, Last.fm similar artists for tracks, and MusicBrainz associated artists`; `feat!: expose Bandcamp stream previews and accept ISRC in queries`.

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

### 2026-11-20 — M-3 evidence (previews and ISRC)

Changed:
- Bandcamp: `TrackInfo.file`; `parse.stream_url()` takes the `mp3-128` stream of a track page's track (the trackinfo with the page's id, else the only one), only `https` on a `.bcbits.com` host, and puts it on the track link's `preview_url`. Album pages give none; a compilation track keeps its stream. `Capability.PREVIEWS` on the adapter. No new requests; nothing is downloaded.
- `BandcampSettings.ttl` defaults to 43 200 s (12 h); `.env.example` updated.
- Merge: links with the same URL keep a `preview_url` that a later source gives (`_combine_links`). Before, the first link won, so a MusicBrainz link without a preview hid the preview of iTunes, Spotify, Deezer, or Bandcamp for the same URL.
- `IdKind.ISRC`. `normalize_code` moved from `core/normalize.py` to `core/query.py` (R5 puts `query` below `normalize`); the public name is unchanged. New `isrc_code()` (normalize, then `^[A-Z]{2}[A-Z0-9]{3}\d{7}$`, else `InvalidQueryError`) and `isrc_ids()` in `deadwax.core`. `Query` normalizes `ids[isrc]` and rejects an ISRC on an album query. `text_query(..., isrc=)`, `parse_query(..., isrc=)` for text and URL queries.
- `LookupContext.isrcs()`: the query's ISRC first, then the identity's, without repeats. MusicBrainz `_find_by_text` and Spotify `_find_by_code` (tracks) use it.
- CLI `--isrc CODE`; a malformed code or `--album --isrc` is a usage error.
- Docs: `requests.md` (Bandcamp previews and expiry, merged previews, ISRC section), `sources.md` (Bandcamp, MusicBrainz, Spotify), `getting_started.md`, README options and source table.
- Tests:
  - ISRC normalization and rejection: `isrc_code`, `Query`, `text_query`, `parse_query`, CLI.
  - `isrcs()` order and dedupe.
  - The query ISRC finds the MusicBrainz recording without a search, and Spotify searches `isrc:`.
  - Same-URL links keep the later preview.
  - `stream_url` cases; the `missing_remix` and `paranoid_android` pages.
  - A `previews`-only request replays `missing_remix` through the client with Bandcamp's stream on its track link.
  - The Bandcamp TTL default.

Decisions:
- (agent) The Bandcamp TTL is 12 hours. In `missing_remix` the stream URL's `ts` (also the `token` prefix) is the fetch time + 86 398 s, so the URL expires about a day after the fetch. A 12-hour page cache leaves a returned URL at least about 12 hours of life. Consumers that play later need a new lookup.
- (agent) The ISRC check is the full ISRC form, not only the length. The query ISRC is input: it is not copied into `identity.isrcs`, which lists only what sources report.
- (agent) `parse_query` raises `InvalidQueryError`; constructing `Query` directly raises Pydantic's `ValidationError` (both are `ValueError`).
- (agent) No fixtures were re-recorded: no new URL is requested.

Observations:
- Of the Bandcamp fixtures, only `missing_remix` (track page) and the Huerco S. album page carry streams. The Radiohead track pages have `file: null`, and the Kino track has an empty `file`. The `bandcamp.com/stream_redirect` URLs in the fixtures belong to recommendations, not to `data-tralbum`.
- MusicBrainz runs in the identity pass, so before M-3 `identity.isrcs` was always empty there; the query's ISRC is the first input that reaches its `isrc/` lookup.

Checks: `uv sync --all-groups --locked`; `uv run poe check` passed (fmt-check, lint, lint-imports 16 contracts kept, mypy, 1143 tests, coverage 96.99%; the touched core modules, `services.py`, and the CLI are fully covered). `uv run --group docs properdocs build --strict` passed. `uv build`; wheel smoke: the base install imports `Deadwax` and builds an ISRC query, and the `cli` extra shows `--isrc`. `uv run poe audit`: no known vulnerabilities. Mock-tested only (no live runs): Bandcamp streams, ISRC lookups, preview merging.

**Suggested message:** `feat!: expose Bandcamp stream previews and accept ISRC in queries`.

### 2026-11-20 — M-2 evidence (leads)

Changed:
- `RelationKind.SIMILAR_ARTIST_RECORDING` and `RelationKind.ASSOCIATED` in `core/models.py`; the CLI renders relation kinds generically, so only `docs/output.md` gained rows (and the sample-offset note moved below the relation table it had split).
- ListenBrainz: for a track with an artist MBID and `relations` wanted, `GET /1/lb-radio/artist/{mbid}` (`mode=easy`, `max_similar_artists`, `max_recordings_per_artist`, `pop_begin=0`, `pop_end=100`); list values flattened in response order, the seed artist's recordings dropped, at most 40 resolved through `GET /1/metadata/recording/?inc=artist`; unnamed items dropped. Relations `similar_artist_recording`, target recording with MB URL and ID, scope `artist`, provenance the LB artist page. Settings `sources.listenbrainz.radio_artists` (8) and `radio_per_artist` (2) with `.env.example` lines.
- Last.fm: `artist.getSimilar` (10) also for tracks, after `track.getSimilar`; one `_similar_artists` helper for tracks and albums.
- MusicBrainz: `member_relations` → `artist_relations`; `member of band` stays `member`/`project`; is person, collaboration, supporting / vocal / instrumental supporting musician, subgroup, founder, artist rename, tribute, and producer give `associated` with `note` = type, or `type: attributes`; response order kept.
- Docs: `output.md`, `sources.md` (MusicBrainz, Last.fm, ListenBrainz), `requests.md` example, README source table.
- Tests: LB Radio parameters and settings, seed artist dropped, 40-MBID cap, empty radio and seed-only radio make no metadata request, no radio without an artist MBID or for albums or without `relations`; Last.fm track similar artists and facet skipping; `artist_relations` mapping and order; the `paranoid_android` replay yields all three lead types.
- Fixtures: `listenbrainz` (13 scenarios) and `lastfm` (10 scenarios) re-recorded live on 2026-11-20 with `uv run --env-file .env python scripts/record_fixtures.py --live listenbrainz,lastfm`; existing replay assertions held on the newer data. The Last.fm key does not appear in the fixtures.

Decisions:
- (agent) MusicBrainz fixtures are not re-recorded: the adapter already requested `artist/{id}?inc=artist-rels`, and the 12 recorded responses contain the needed types (`artist rename`, `subgroup`, `supporting musician`, `tribute`, `founder`, `instrumental supporting musician`, `collaboration`, `is person`) and excluded ones (`married`, `parent`, `involved with`). Keeping them keeps the MBIDs that ListenBrainz requests depend on.
- (agent) The radio target's artist is the recording's artist credit from the metadata endpoint, falling back to LB Radio's similar-artist name: live, a recording listed for Green Day is credited to the *American Idiot* cast. V1 used the similar-artist name.
- (agent) No special error handling for LB Radio: an artist without radio data answers `200 {}` live (checked with the nil MBID), which gives no relations.
- (observation) `tribute` relations of MusicBrainz are mostly tribute bands of the artist (backward direction); they are kept as in V1, with the type in the note so consumers can rank or drop them.

Observations:
- `scripts/record_fixtures.py` forwards every source without fixtures to the network whatever `--live` says, because the recording lookup includes every group. The run therefore also sent plain requests to Beatport, Juno, Bleep, Forced Exposure, AllMusic, Album of the Year, NTS, WFMU, RA, and one artist site (`djtramaine713.com`), and wrote fixture directories for them and Last.fm fixtures for three scenarios that had none; all of these untracked files were deleted. Restricting the recorder to the live sources plus those with fixtures is left for a later change.

Checks: `uv sync --all-groups --locked`; `uv run poe check` passed (fmt-check, lint, lint-imports 16 contracts kept, mypy, 1104 tests, coverage 96.97%); `uv run --group docs properdocs build --strict` passed. Live (2026-11-20): `deadwax lookup "Radiohead - Paranoid Android" --track --sources musicbrainz,listenbrainz,lastfm --facets identity,relations --no-cache -f json` gave 12 `similar_artist_recording` (ListenBrainz), 10 similar artists and 20 similar tracks (Last.fm), 12 `associated` and 5 `member` (MusicBrainz), no errors. Mock-tested only: the 40-MBID cap, the seed-only and empty radio paths, and attribute notes on associated relations.

**Suggested message:** `feat(sources)!: add LB Radio, Last.fm similar artists for tracks, and MusicBrainz associated artists`.

### 2026-11-20 — M-1 evidence (requests and client)

Changed:
- `core/request.py`: `Request(query, facets, tags_per_source, relations)` and `RelationLimit(kind, target, per_source)`; caps without their facet are rejected. `core/select.py`: `trim()` empties facets not requested, keeps only preview links for `previews` without `links`, caps tags per first source and relations per first source, kind, and target type. R5 contract: `orchestrator | select` above `request` above `adapter | merge`.
- `Capability.PREVIEWS` on iTunes, Spotify, and Deezer (Bandcamp follows in M-3 with its stream URL).
- Orchestrator: `LookupOptions.facets`; an adapter runs when it is in the identity pass, resolves the query URL, or contributes a requested facet other than `identity`; the trace event `lookup.selected` gains `facets`. `LookupContext.facets` and `wants()`.
- `sources/client.py`: `Deadwax`, an async context manager holding the response cache and `HttpResources` (per-host limiters, browser sessions) for its life; adapters are built and closed per lookup. `lookup()` opens a client for one call and accepts a `Query` or a `Request`. R4 contract: `client` below `lookup`. Docstrings of `HttpResources` and `BrowserSessions` say they live as long as the client.
- Last.fm skips top tags without `tags` and similar items without `relations`; ListenBrainz skips popularity, similar items, and reviews without `metrics`, `relations`, `texts`; MusicBrainz skips the artist-relations request and Bandcamp the label page without `relations`.
- CLI `--facets` (comma-separated, like `--sources`); an unknown facet is a usage error.
- Exports `Request`, `RelationLimit`, `Deadwax` (lazy). Docs: new `docs/requests.md` page, architecture layers and lookup flow, getting started, README, API reference index.

Decisions:
- (agent) Adapters are built per lookup rather than once per client: per-lookup state (Spotify token, escalation level, headed fallback of a client) stays valid without refresh logic, while limiters, cache, and browsers are shared. This replaces the planned Spotify token refresh. A browser session upgraded to headed stays headed for the client's life.
- (agent) `include`/`exclude` stay arguments of `lookup()`, not `Request` fields: the request names data, the caller and configuration name sources.
- (agent) Review links belong to the `texts` facet.

Checks: `uv run poe check` passed (fmt-check, lint, lint-imports 16 contracts kept, mypy, 1098 tests, coverage 96.95%; `core/request.py`, `core/select.py`, `sources/client.py` fully covered); `uv run --group docs properdocs build --strict` passed. No live runs: the stage changes selection and composition, and replayed fixtures cover facet selection (`tests/sources/test_client.py`).

**Suggested message:** `feat!: request dossiers by facets through a long-lived Deadwax client`.

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
