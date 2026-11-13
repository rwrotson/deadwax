# deadwax v2: implementation plan and handoff journal

## Status and handoff

This is the active specification and multi-session handoff for deadwax. deadwax collects, for one track or album, what open sources know about that exact recording, with four goals: (1) texts describing its sound, (2) relations for further searches, (3) confirmation of the exact recording and version with visible discrepancies, (4) streaming links. v1 (eight sources) is complete; its plan, stage evidence, and full decision log are archived in [`plans/v1.md`](plans/v1.md).

- **Status:** v1 complete and committed. v2 source scope recorded (`## v2 sources`); v2 stages 8–20 defined; Stages 8–9 done; Stage 10 next.
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

Never used: Every Noise at Once, direct Metacritic scraping (ratings come from Wikipedia), Spotify audio features.

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
| Shops | Phonica | staff `shop` texts; genres | HTML |
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
| Streaming | Juno Download | BPM; genre; label | HTML |
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
| 10 | Not started | Spotify, YouTube (links only), SoundCloud. |
| 11 | Not started | Beatport, Juno Download; BPM and key. |
| 12 | Not started | Shops I: Juno, Hard Wax, Phonica, Soundohm; shop-text deduplication. |
| 13 | Not started | Shops II: Boomkat, Norman Records, Forced Exposure, Bleep. |
| 14 | Not started | Genius. |
| 15 | Not started | Reviews I: AllMusic, Album of the Year. |
| 16 | Not started | Reviews II: press adapter with per-site rules, Resident Advisor. |
| 17 | Not started | Radio: NTS, WFMU; context tags. |
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

- [ ] Spotify with client credentials: links, popularity, label, copyrights, ISRC; resolves Spotify URLs.
- [ ] YouTube with a Data API key: links only (official uploads first), no facts.
- [ ] SoundCloud through the web client: uploader descriptions, tags, counts, reposters as relations; resolves SoundCloud URLs.

**Acceptance:** missing credentials give `skipped`; YouTube contributes nothing but links. **Suggested message:** `feat(sources): add Spotify, YouTube and SoundCloud adapters`.

### Stage 11: Beatport, Juno Download

- [ ] Model: BPM and key as sourced identity values with discrepancies.
- [ ] Version detection: mix names (Original, Extended, Dub, Radio Edit…) mapped to versions.
- [ ] Beatport from `__NEXT_DATA__`: BPM, key, subgenre, mix name, ISRC, remixers, DJ charts as relations.
- [ ] Juno Download: BPM, genre, label.

**Acceptance:** an Extended Mix is not merged into the Original Mix; a BPM disagreement is a discrepancy. **Suggested message:** `feat(sources): add Beatport and Juno Download adapters with BPM and key`.

### Stage 12: shops I

- [ ] Juno, Hard Wax, Phonica, Soundohm through the Stage 8 helper: `shop` texts, genres, "also bought" as `similar` where present.
- [ ] Merge: `shop` texts that repeat one press release are deduplicated, keeping every source.

**Acceptance:** the same press text from two shops appears once with both sources. **Suggested message:** `feat(sources): add Juno, Hard Wax, Phonica and Soundohm adapters`.

### Stage 13: shops II

- [ ] Boomkat (Cloudflare, escalation ladder), Norman Records, Forced Exposure, Bleep: `shop` and `label` texts, genres, related releases as `similar`.

**Suggested message:** `feat(sources): add Boomkat, Norman Records, Forced Exposure and Bleep adapters`.

### Stage 14: Genius

- [ ] Decide with the user whether lyrics are stored, before the stage.
- [ ] Genius API with a token: description and annotations as texts, credits, samples, interpolations, covers, and remixes as directional relations; lyrics from HTML only if decided.

**Suggested message:** `feat(sources): add Genius adapter`.

### Stage 15: reviews I

- [ ] AllMusic: review with rating and critic, moods and themes as `mood`/`theme` tags, styles, credits, similar albums.
- [ ] Album of the Year: critic scores per publication, user score, genres; review links carried in the context for Stage 16, with MusicBrainz review links.

**Acceptance:** an AllMusic score from Wikipedia's ratings template and from AllMusic itself merge into one review. **Suggested message:** `feat(sources): add AllMusic and Album of the Year adapters`.

### Stage 16: reviews II

- [ ] Decide with the user how much review text is kept, before the stage.
- [ ] Press adapter: one adapter, per-site rules (Pitchfork, The Quietus, The Wire, and others agreed at the stage) reading review links from the context.
- [ ] Resident Advisor through its GraphQL endpoint: reviews, artist and label bios, DJ charts as relations.

**Suggested message:** `feat(sources): add press review and Resident Advisor adapters`.

### Stage 17: radio

- [ ] Model: tags of an episode or set marked as context rather than the track's own.
- [ ] NTS: episodes that played the track as `broadcast`, neighbouring tracks, episode genres as context tags.
- [ ] WFMU: playlists as `broadcast`, DJ comments as texts.

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

### 2026-11-13 — Stage 8 evidence

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

**Current task:** Stage 10 (Spotify, YouTube, SoundCloud). **Next action:** at the start of Stage 10, verify each source's access notes.

## Resume instructions

> Read `AGENTS.md`, `docs/architecture.md`, and `DEADWAX_PLAN.md`. Inspect the branch, worktree, stage table, and latest evidence. Implement the first incomplete stage only, preserving accepted and standing decisions and import rules. Run the stage checks, append dated evidence, update the status only when acceptance passes, report an English commit message, stop at the stage boundary, and do not create commits.

Distinguish planned, implemented, mock-tested, and live-verified behaviour in every handoff.
