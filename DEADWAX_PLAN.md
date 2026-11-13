# deadwax v2: implementation plan and handoff journal

## Status and handoff

This is the active specification and multi-session handoff for deadwax. deadwax collects, for one track or album, what open sources know about that exact recording, with four goals: (1) texts describing its sound, (2) relations for further searches, (3) confirmation of the exact recording and version with visible discrepancies, (4) streaming links. v1 (eight sources) is complete; its plan, stage evidence, and full decision log are archived in [`plans/v1.md`](plans/v1.md).

- **Status:** v1 complete and committed. v2 source scope recorded (`## v2 sources`); v2 stages 8–20 defined; Stage 8 next.
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
| 8 | Not started | Foundation: source groups, default source set, per-lookup concurrency cap, shared search → page helper. |
| 9 | Not started | ListenBrainz, SecondHandSongs, KEXP. |
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

- Fixture tests for every extraction path, and for not found, blocked, and a missing key where one applies.
- The matching gate drops a candidate of another version (tested).
- Every new setting has a description and a line in `.env.example`; the source is described in `docs/sources.md` and the README tables.
- `uv run poe check` and the strict docs build pass.
- Live runs on the five v1 check records and at least one record the source is strong on; the report separates mock-tested from live-verified behaviour.

### Stage 8: foundation

- [ ] Source groups (`shops`, `press`, `catalogues`, `radio`, `streaming`, `samples`, and the v1 sources as `core`) accepted by `--sources` and `--exclude` and shown by `deadwax sources`.
- [ ] The default set of enabled sources, decided with the user at the start of the stage (a full lookup would otherwise query 34 sources).
- [ ] A per-lookup cap on concurrent adapters (setting), so a lookup with every source stays within rate limits.
- [ ] A shared helper in `sources/_base.py` for HTML sources that search, pick a candidate through the matching gate, and read its page.

**Acceptance:** orchestrator and CLI tests for groups, the default set, and the cap; the helper tested with a fake source. **Suggested message:** `feat(sources): add source groups and a concurrency cap for v2 sources`.

### Stage 9: ListenBrainz, SecondHandSongs, KEXP

- [ ] ListenBrainz by MBID: similar recordings and artists, listen counts; CritiqueBrainz reviews as `user` texts.
- [ ] SecondHandSongs: original and first release, writers, covers and adaptations as directional relations.
- [ ] KEXP: plays as `broadcast` relations with dates; DJ comments as texts.

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

**Current task:** Stage 8 (foundation). **Next action:** user review of the v2 stages; at the start of Stage 8, decide the default source set with the user.

## Resume instructions

> Read `AGENTS.md`, `docs/architecture.md`, and `DEADWAX_PLAN.md`. Inspect the branch, worktree, stage table, and latest evidence. Implement the first incomplete stage only, preserving accepted and standing decisions and import rules. Run the stage checks, append dated evidence, update the status only when acceptance passes, report an English commit message, stop at the stage boundary, and do not create commits.

Distinguish planned, implemented, mock-tested, and live-verified behaviour in every handoff.
