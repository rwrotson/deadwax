# deadwax v2: implementation plan and handoff journal

## Status and handoff

This is the active specification and multi-session handoff for deadwax. deadwax collects, for one track or album, what open sources know about that exact recording, with four goals: (1) texts describing its sound, (2) relations for further searches, (3) confirmation of the exact recording and version with visible discrepancies, (4) streaming links. v1 (eight sources) is complete; its plan, stage evidence, and full decision log are archived in [`plans/v1.md`](plans/v1.md). The v2 source scope, closed v2 stages (8–17, 19, 20, R-1–R-6, M-1–M-3), their evidence, the Stage 18 access attempts, and the v2 decision log are archived in [`plans/v2.md`](plans/v2.md).

- **Status:** v1 and v2 complete; v0.1.0 is the first tagged release (2026-11-20, GitHub only, no PyPI). Stage 18 (Rate Your Music) deferred until RYM is accessible; Boomkat and Norman Records remain access-limited. Stages E-1–E-3 (artist, label, and other record kinds): E-1 and E-2 done, E-3 in progress (step 1 of 6 done: groundwork and MusicBrainz).
- **Branch:** `main`. Agents never create commits on the user's behalf.
- **Working rule:** complete one stage, run its acceptance checks, append dated evidence, update the status table, report an English Conventional Commit suggestion, and stop. Resume the next stage only when the user asks.
- Read `AGENTS.md` (and the nested `AGENTS.md` of the area you change), `docs/architecture.md` (import rules R1–R9), and `CONTRIBUTING.md` before code changes. After code changes run `uv run poe check`; after docs or public docstring changes also run `uv run --group docs properdocs build --strict`.
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
| Record kinds | Adapters dispatch by record kind through `Lookups`, one optional slot per kind (`track`, `album`, `artist`, `label`, `unresolved`), each typed by its query; identities and candidates are unions by kind (2026-11-21): a typed visitor whose methods may be absent, so a new kind breaks no adapter and the orchestrator sees which kinds a source supports. Classic Visitor, `singledispatch`, and a global dispatch table were weighed and rejected (2026-11-21). |
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
- Deezer stays in the `core` group but not in `DEFAULT_SOURCES`: Akamai blocks it on every route (2026-11-19).

## Implementation stages and acceptance criteria

Numbering continues after v1 (stages 0–7 in `plans/v1.md`). Sections of closed stages are in `plans/v2.md`. Order: shared infrastructure first; clean APIs next, to prove it; each model addition lands in the first stage whose source needs it; sources behind bot protection or with open terms-of-service questions last, so those decisions can be made meanwhile.

| Stage | Status | Deliverable |
| --- | --- | --- |
| 8–17, 19 | Done | v2 sources (details and caveats in `plans/v2.md`). |
| 18 | Deferred (RYM access blocked) | Provisional Rate Your Music adapter and browser-first fetching; parser and live results unverified. |
| R-1–R-6 | Done | Structural refactoring: adapter packages, shared helpers, service catalogue, configuration, core, cleanup. |
| M-1–M-3 | Done | Requests by facets and the `Deadwax` client, leads, Bandcamp previews and ISRC. |
| 20 | Done (RYM blocked, Forced Exposure HTTP 403, Norman disabled by the local allowlist) | Qualification; release v0.1.0. |
| E-1 | Done | Per-kind lookup slots (`Lookups`), dispatch by the kind known in each pass, `SourceInfo.kinds`. |
| E-2 | Done | Typed queries per kind, a model for artists and labels, CLI `--artist` and `--label`. |
| E-3 | In progress (MusicBrainz done) | Artist and label lookups, MusicBrainz, Discogs, Last.fm, Wikipedia, and Bandcamp first. |

Common acceptance for source stages (9–19, and source work in E-3), in addition to each stage's own:

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

**Deferred until:** RYM search and record pages can be captured and live lookups run. Do not mark this stage done from synthetic fixtures. The 2026-11-16 access attempts are in `plans/v2.md`.

**Suggested message:** `feat(sources): add Rate Your Music adapter`.

### Stages E-1–E-3: record kinds

Agreed with the user on 2026-11-21. deadwax will look up artists and labels, and possibly works, besides tracks and albums; sources support them selectively. Breaking changes carry `!`. Each stage passes `uv run poe check` and the strict docs build and ends with evidence and a commit suggestion.

- **E-1 (dispatch, no new kinds).** `core.Lookups` with optional `track`, `album`, and `unresolved` slots replaces `Adapter.lookup`; `HttpAdapter.lookup` remains as a convenience that runs the slot of `LookupContext.kind`. The orchestrator drops adapters without a slot for the query's kind at selection (`lookup.selected.unsupported`), dispatches each pass on the kind known so far (`pass.start.kind`, `pass.start.unsupported`), and picks a resolver only among adapters with a slot for the query's kind. Track-only sources declare only `track` instead of refusing albums with `not_found` or an empty partial. `SourceInfo.kinds` and a `kinds` column in `deadwax sources`.
- **E-2 (model).**
  - `Query` becomes a union discriminated by `kind`: `TrackQuery`, `AlbumQuery`, `ArtistQuery`, `LabelQuery`, and `UnresolvedQuery` for a URL whose kind only a resolver finds; slots are typed by their query.
  - A matching key for names (artist, label) beside `RecordKey`; `Identity` and `RecordCandidate` split into common and per-kind parts (decide the shape with the user first); merge orders for the new kinds; `Capability` meanings for artists and labels.
  - URL rules for artist and label pages; CLI `--artist`, `--label`; README, docs, `.env.example`.
- **E-3 (sources).** `artist` and `label` slots, MusicBrainz, Discogs, Last.fm, Wikipedia, and Bandcamp first; live invariants for the new kinds in `tests/integration`.

**Suggested messages:** `refactor!: dispatch adapter lookups by record kind`; `feat!: add typed queries and a model for artists and labels`; E-3 at its end.

### Later, unscheduled: automation masking for Cloudflare-protected sources

- [ ] Masking browser automation (stealth plugins, undetected-chromedriver, nodriver, Camoufox, fingerprint spoofing) so that Beatport and similar sources pass Cloudflare challenges that defeat httpx, curl_cffi, and plain Playwright.

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

### 2026-11-21 — E-3 progress, step 1 (groundwork and MusicBrainz)

Decisions (user, 2026-11-21):
- New relation kinds `alias`, `parent_label`, `sublabel` (directional), and `release` (main releases of the queried artist, capped); label discographies reuse `label_release`.
- E-3 runs in six steps with a pause and commit suggestion after each: groundwork and MusicBrainz; Discogs; Last.fm (artists only, the API has no label methods); Wikipedia; Bandcamp; live invariants, docs, closing evidence.
- Bandcamp gets artist and label slots; subdomain roots resolve to an artist or label only if a live check finds a reliable marker, otherwise they stay unresolved.
- MusicBrainz is the hub for names as for records: enrichment sources take Discogs, Wikidata, and Bandcamp IDs and links from it and search by name only without them.

Changed:
- `core/models.py`: `RelationKind.ALIAS`, `PARENT_LABEL`, `SUBLABEL`, `RELEASE`; `associated` now also covers label-to-artist relations.
- `sources/_search.py`: `name_key` (query name, else the name of an earlier pass for a URL query, with the known IDs).
- MusicBrainz: `artist` and `label` slots; resolves its artist and label pages; MBID from the query or earlier passes, any URL through `ws/2/url`, else a name search ranked with `compare_names`. Artists: candidate with type, country, life span, Discogs artist and Wikidata IDs; tags, aliases (no search hints), artist relations, `recording contract` labels, up to 25 official albums and EPs without secondary types (`release-group` browse with `release-group-status=website-default`, skipped without the relations facet), links. Labels: hierarchy from `imprint` and `label ownership`, related artists as `associated`, aliases, tags, links.
- Fixtures `aphex_twin`, `warp`, `musicbrainz_artist_url` (MusicBrainz only, recorded live 2026-11-21); tests in `tests/sources/adapters/musicbrainz/test_names.py`, `tests/sources/test_lookup_names.py`, `name_key` tests; docs: sources, output relation table, README, getting started.

Checks: `uv run poe check` passed (1240 tests, coverage 97.08%); `uv run --group docs properdocs build --strict` passed. Live: `deadwax --artist "Aphex Twin" --sources musicbrainz --no-cache` and `deadwax --label Warp --sources musicbrainz --no-cache` give the expected identity, relations, and links; the Warp MusicBrainz URL resolves.

Remaining: steps 2–6.

### 2026-11-21 — E-2 evidence (typed queries, artists and labels)

Decisions (user, 2026-11-21):
- `Identity` and the candidate are unions discriminated by `kind` with a common base (`IdentityBase`: `kind`, `external_ids`, `discrepancies`), not one identity with nested per-kind parts and not a flat identity with an extra `name`.
- Artists and labels get a base field set now, before any source fills it: `name`, `disambiguation`, `country`, `begin`, `end`; artists also `type` (`ArtistType`).
- `--artist` and `--label` take the whole text as the name. A query of a kind no selected source looks up gets an explicit `unsupported` error (source `deadwax`) instead of an empty dossier.

Changed:
- `core/query.py`: `EntityKind.ARTIST`, `LABEL`; `IdKind.BEATPORT_ARTIST`, `BEATPORT_LABEL`; `Query` is a discriminated union of `TrackQuery`, `AlbumQuery`, `ArtistQuery`, `LabelQuery`, `UnresolvedQuery` (callable discriminator, since `None` cannot be a literal tag); `with_kind` promotes a URL query to the kind found later (dropping an ISRC that does not fit), `url_query`; `text_query` builds every kind; an ISRC is rejected on all but tracks.
- `core/models.py`: `RecordIdentity`, `ArtistIdentity`, `LabelIdentity` (`Identity` union, `found` per class); `RecordCandidate` (kind checked to be track, album, or unknown), `ArtistCandidate`, `LabelCandidate` (`Candidate` union); `ErrorKind.UNSUPPORTED`.
- `core/adapter.py`: slots typed by their query (`TrackLookup` … `UnresolvedLookup`), `Lookups.artist`, `label`; `Lookups.bind(query)` replaces `get`, `supports(kind)`; `Capability` meanings for artists and labels.
- `core/matching.py`: `NameKey`, `compare_names` (a shared identifier namespace decides, else name similarity; `MATCH` or `NO_MATCH` only). `core/merge.py`: reference and judgement per family, a record and a name never match; name identities by consensus with discrepancies on name, disambiguation, country, begin, end, type, and ids; scope and link orders for artists and labels. `core/orchestrator.py`: `unsupported` error, each pass's context query promoted with `with_kind`, `pass.start` identity summary per class.
- `sources`: URL rules for MusicBrainz and Discogs artist and label pages, Spotify, Deezer, and Apple Music artist pages, Beatport artist and label pages; `link_target` maps them. Last.fm and Resident Advisor have no service entry, so their artist URLs wait for E-3; Bandcamp subdomain roots stay unresolved (artist or label). `search_key`, Spotify, Deezer, 1001Tracklists narrowed to record types; adapters keep `query: Query` signatures, which fit the typed slots.
- CLI: `--artist`, `--label`, mutually exclusive with `--track` and `--album`; pretty and Markdown output of artist and label identities (`cli/text.py`: `identity_title`, `query_text`, `name_fields`). Run journal names artists and labels.
- Tests: typed constructors throughout; new tests for query kinds and promotion, JSON round trips per kind, name matching, name merges, `unsupported`, URL rules, CLI flags and rendering, run records. Docs: output, requests, architecture, runs, getting started, README.

Checks: `uv run poe check` passed (fmt-check, lint, lint-imports 16 kept, mypy 297 files, 1220 tests, coverage 97.04%); `uv run --group docs properdocs build --strict` passed. Manual: `deadwax --artist "Aphex Twin"` and a MusicBrainz artist URL end with `deadwax  unsupported` and exit 3; `--artist … --isrc …` and `--artist --label` exit 2; `deadwax --track "Burial - Archangel" --sources musicbrainz,itunes,lastfm,discogs --no-cache` gives the same identity as before (live).

Remaining: E-3 (artist and label slots in MusicBrainz, Discogs, Last.fm, Wikipedia, Bandcamp; their URL rules; live invariants).

**Suggested message:** `feat!: add typed queries and a model for artists and labels`.

### 2026-11-21 — E-1 evidence (per-kind lookup slots)

Decision (user, 2026-11-21): of the five Visitor variants weighed (methods on nodes, pattern matching, classic Visitor, dispatch matrix, `singledispatch`), none fits as is: there is no tree to traverse, and the adapter × kind matrix is sparse, so a classic Visitor would force every adapter to implement every kind. Chosen: a typed slot per kind on each adapter (`Lookups`), one `match` in the core, slots typed by per-kind queries from E-2.

Changed:
- `core/adapter.py`: `KindLookup`, `Lookups` (`get`, `kinds`), `LookupContext.kind`, `SourceInfo.kinds`; `Adapter.lookups` replaces `Adapter.lookup`.
- `core/orchestrator.py`: selection drops adapters without a slot for a known query kind; each pass dispatches on `LookupContext.kind`; the resolver must have a slot for the query's kind.
- `sources`: `HttpAdapter.lookups` is abstract and `HttpAdapter.lookup` dispatches; `SearchPageAdapter.find` fills all three slots. Tracks only: Genius, SecondHandSongs, NTS, WFMU (`track`), 1001Tracklists and WhoSampled (`track`, `unresolved`); their album refusals are removed. Last.fm and ListenBrainz split into track and album lookups. Adapters that read their own URLs, plus Odesli and Wikipedia, keep an `unresolved` slot; the others no longer guess a kind when none is known.
- CLI: `deadwax sources` shows a kinds column. Docs: architecture lookup flow and adding a source, run events, sources.

Behaviour change: an album query no longer runs the track-only sources, so their `not_found` errors and empty partials disappear; with an unknown kind after a pass, sources without an `unresolved` slot sit the pass out instead of searching as a track.

Checks: `uv run poe check` passed (fmt-check, lint, lint-imports, mypy, 1149 tests, coverage 97.00%); `uv run --group docs properdocs build --strict` passed. Live lookups were not run: dispatch for track and album queries is unchanged apart from the cases above.

Remaining: E-2 (typed queries and the model for new kinds), E-3.

**Suggested message:** `refactor!: dispatch adapter lookups by record kind`.
