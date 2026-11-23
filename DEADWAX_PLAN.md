# deadwax v2: implementation plan and handoff journal

## Status and handoff

This is the active specification and multi-session handoff for deadwax. deadwax collects, for one track or album, what open sources know about that exact recording, with four goals: (1) texts describing its sound, (2) relations for further searches, (3) confirmation of the exact recording and version with visible discrepancies, (4) streaming links. v1 (eight sources) is complete; its plan, stage evidence, and full decision log are archived in [`plans/v1.md`](plans/v1.md). The v2 source scope, closed v2 stages (8–17, 19, 20, R-1–R-6, M-1–M-3), their evidence, the Stage 18 access attempts, and the v2 decision log are archived in [`plans/v2.md`](plans/v2.md).

- **Status:** v1 and v2 complete; v0.1.0 is the first tagged release (2026-11-20, GitHub only, no PyPI). Stage 18 (Rate Your Music) deferred until RYM is accessible; Boomkat and Norman Records remain access-limited. Stages E-1 and E-2 are done. E-3 artist and label lookups and their six live scenarios are verified. Closing E-3 awaits a completed standard live suite.
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
- The default set includes every current adapter configured to start without a visible browser. Boomkat, Norman Records, WhoSampled, and 1001Tracklists remain opt-in (2026-11-23).

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
| E-3 | In progress (standard live suite pending) | Artist and label lookups in MusicBrainz, Discogs, Last.fm, Wikipedia, and Bandcamp. Live invariants and documentation. |

Common acceptance for source stages (9–19, and source work in E-3), in addition to each stage's own:

- The adapter declares its `group`. The default set is defined in `sources/config.py`.
- An HTML source that searches and reads one page builds on `SearchPageAdapter` in `sources/_search.py` (formerly `_base.py`), or the evidence says why not.

- Fixture tests for every extraction path, and for not found, blocked, and a missing key where one applies.
- The matching gate drops a candidate of another version (tested).
- Every new setting has a description and a line in `.env.example`; the source is described in `docs/sources.md` and the README tables.
- `uv run poe check` and the strict docs build pass.
- Live runs on the five v1 check records and at least one record the source is strong on; the report separates mock-tested from live-verified behaviour.

### Stage 18: Rate Your Music

- [x] The user confirmed express permission for automated RYM access.
- [x] Browser-first fetching for a source that never answers plain httpx.
- [ ] Verify primary and secondary genres, descriptor tags, rating with vote count, chart positions, and user reviews against real RYM pages. The provisional parser is covered only by synthetic HTML.

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

### 2026-11-22 — Claude Code hook maintenance

The Stop hook now compares dirty Python state before and after the turn. Both check hooks report bounded failure diagnostics and stay silent on success. E-3 is unchanged.

Checks: `bash -n`, `jq -e`, and `git diff --check` passed. Synthetic hook events in a temporary Git repository passed, including Bash edits to an already dirty file, session and worktree isolation, and bounded failure output. `uv run poe check` passed (1240 tests, 97.09% coverage). Live tests were not run; this change does not touch adapters.

### 2026-11-23 — E-3 progress, step 2 (Discogs)

Discogs now looks up artists and labels by direct URL, IDs from earlier passes, or token-authenticated name search. It adds profile text and links, artist members, groups and aliases, label hierarchy, and up to 12 main masters or catalog releases per lookup. Text name queries use the identifiers of the first matching candidate at the merge gate. This lets MusicBrainz's Warp match Discogs's Warp Records (23528) while rejecting namesakes with another ID in the shared namespace.

Recorded five Discogs scenarios with `scripts/record_fixtures.py --live discogs`: `aphex_twin`, `warp`, and `musicbrainz_artist_url` with `--sources musicbrainz,discogs`, and `discogs_artist_search` and `discogs_label_search` with `--sources discogs`. Verified that the recordings contain no configured token. Replay tests exercise the library entry point. Mock responses cover missing credentials, empty search, 404, challenge pages, and discography filtering.

Live, uncached CLI checks found Aphex Twin and Warp by name and by Discogs URL, including both direct URLs without a token, and confirmed Discogs enrichment for the Aphex Twin MusicBrainz URL. Discogs-only search for Warp selected the exact listing (1038614), while MusicBrainz supplied the Warp Records ID (23528) for the combined lookup. The five v1 records and Burial's Archangel returned identities. Discogs review pages were blocked for Paranoid Android, Huerco S., Missing, and Archangel. Discogs timed out for Kino and reported no match in its catalog for the underground album, which Bandcamp found.

Checks: `uv run poe check` passed (1252 tests, 97.13% coverage) and `uv run --group docs properdocs build --strict` passed. The first run exhausted disk space. The successful run disabled disposable tool caches and used four test workers. `poe test-live` was deferred to step 6 with the new live invariants.

Remaining: steps 3–6.

### 2026-11-23 — E-3 progress, step 3 (Last.fm)

Last.fm now looks up artists by MusicBrainz artist ID, name, or Last.fm artist profile URL. It contributes the identity, biography, weighted tags, similar artists, and lifetime listener and scrobble counts. The README and source guide describe these additions.

Recorded four Last.fm scenarios with `scripts/record_fixtures.py --live lastfm`. The `aphex_twin` and `musicbrainz_artist_url` scenarios replay MusicBrainz with `--sources musicbrainz,lastfm`. The `lastfm_artist_search` and `lastfm_artist_url` scenarios use `--sources lastfm`. Verified that the recordings contain no configured key. Replay tests cover the lookup routes and fact provenance. Mock responses cover a mismatched MBID, missing credentials, a not-found response, percent-encoded names, and a metrics-only request with a zero listener count and an absent scrobble count.

Live CLI lookups with `--no-cache` found Aphex Twin by name and by Last.fm URL, and Last.fm contributed the same kinds of facts when MusicBrainz supplied the MBID. Each returned a biography, ten weighted tags, ten similar artists, and both metrics from Last.fm. Last.fm found all five v1 control records and Burial's Archangel without adapter errors.

Checks passed for `uv run --no-sync poe check` (1267 tests, 97.12% branch coverage), `uv run --no-sync --group docs properdocs build --strict`, and `git diff --check`. The full `poe test-live` suite is scheduled for step 6.

Remaining: steps 4–6.

**Suggested message:** `feat(sources): add Last.fm artist lookups`.

### 2026-11-23 — E-3 progress, step 4 (Wikipedia and Wikidata)

Wikipedia now looks up artists and labels by QID, exact MusicBrainz or Discogs ID statement, or a name search filtered by the relevant MusicBrainz ID property. It compares labels and aliases for name searches and verifies exact IDs against the retrieved claims. It adds sourced identity fields and genres, artists' record labels and memberships, label hierarchy, and article leads and sections on history, style, career, and influences. Wikidata country names are kept as supplied, so a name can appear alongside MusicBrainz's country code in a discrepancy.

Recorded Wikimedia responses with `scripts/record_fixtures.py aphex_twin warp --live wikipedia --sources musicbrainz,wikipedia` and `scripts/record_fixtures.py wikipedia_artist_search --live wikipedia --sources wikipedia`. Replay tests cover QID handoff and Russian and English articles for Кино. Mock responses cover all four exact identifier properties, deprecated claims, name mismatches, alias selection, partial dates, and both directions of the label hierarchy.

Uncached CLI checks with Wikipedia found Aphex Twin and Warp by name and via their MusicBrainz and Discogs URLs. Combined MusicBrainz and Wikipedia lookups returned five Wikipedia sections for Aphex Twin and two for Warp. Wikipedia found Paranoid Android, the Huerco S. album, and «Группа крови». It returned `not_found` for the underground album, the Todd Terry remix of Missing, and Burial's Archangel. MusicBrainz identified Archangel in the combined run.

`uv run --no-sync poe check` passed with 1,276 tests and 97.08% branch coverage. The run used four test workers and disabled disposable tool caches to fit the available disk space. `uv run --no-sync --group docs properdocs build --strict` and `git diff --check` passed. The full live suite is scheduled for step 6.

Steps 5–6 remain.

**Suggested message:** `feat(sources): add Wikipedia artist and label lookups`.

### 2026-11-23 — E-3 progress, step 5 (Bandcamp)

Bandcamp looks up artists and labels from a direct account URL, a MusicBrainz link, or autocomplete. The user chose a shared `bandcamp_account` identifier based on the account hostname and a sourced `location` field that preserves the profile's wording. The account identifier lets Bandcamp's Warp Records enrich MusicBrainz's Warp. The boolean `is_label` in `data-band` resolves the kind of an account URL. The adapter adds the profile biography when present, the account link, and up to 12 unique albums from the visible catalogue.

Recorded four direct Bandcamp scenarios with `scripts/record_fixtures.py bandcamp_artist_search bandcamp_label_search bandcamp_artist_url bandcamp_label_url --live bandcamp --sources bandcamp` and two handoff scenarios with `scripts/record_fixtures.py aphex_twin warp --live bandcamp --sources musicbrainz,bandcamp`. The latter replayed MusicBrainz. Search recordings confirmed `item_url_root` and `is_label` on account hits. Mock tests cover a missing or invalid type marker, a type or account ID mismatch, an empty search, the root fallback, the catalogue limit, and facet trimming.

Seven uncached CLI runs with plain HTTP verified both name searches, both MusicBrainz handoffs, both account URL kinds, and the control track Burial — Archangel. The Warp handoff returned the Bandcamp location, account link, and 11 catalogue albums. All seven lookups finished without adapter errors.

`uv run --no-sync poe check` passed with 1,292 tests and 97.02% branch coverage using four workers and disposable tool caches disabled. `uv run --no-sync --group docs properdocs build --strict` and `git diff --check` passed.

Step 6 covers the full `poe test-live` suite, cross-source documentation, and E-3 closing evidence.

**Suggested message:** `feat(sources): add Bandcamp artist and label lookups`.

### 2026-11-23 — Default source selection

At the user's request, added the 16 adapters that start headless or use an API or plain HTTP. The default now selects 29 sources. Boomkat, Norman Records, WhoSampled, and 1001Tracklists remain opt-in. Browser transports and headed fallback retain their existing settings. The replay fixtures and live library corpus keep their previous source coverage.

`uv run --no-sync poe check` passed with 1,292 tests and 97.02% branch coverage. `uv run --no-sync --group docs properdocs build --strict` passed. Both commands used a writable temporary uv cache. `deadwax sources --format json` confirmed 29 defaults and the four opt-in adapters. Live lookups were outside this configuration verification.

**Suggested message:** `feat(sources): expand the default source set`.

### 2026-11-23 — E-3 progress, step 6 (live invariants and documentation)

Added six live scenarios for Aphex Twin, Burial, Кино, Warp, Hyperdub, and the Aphex Twin MusicBrainz URL. They check the typed identity, its MusicBrainz ID, provenance on returned facts and identity values, and support for the query. The live report includes artist and label identities. README and the guides document source coverage, identifier and link handoff, and the `alias`, `release`, `label_release`, `parent_label`, and `sublabel` relations. Step 5's recorded responses and mock tests cover the Bandcamp account kind marker `is_label` and its missing or invalid forms. The live Warp Records account URL resolved to a label and returned catalogue entries.

`uv run --no-sync poe check` passed with 1,292 tests and 97.02% branch coverage, including fixture replay and mocks. `uv run --no-sync --group docs properdocs build --strict` and `git diff --check` passed. The standard `uv run --no-sync poe test-live` with network access collected 29 cases and passed all six new scenarios before disk exhaustion prevented completion of the existing track corpus. A rerun with in-memory output capture again passed the six new scenarios and reported HTTP 503 from MusicBrainz on the first existing track case, Oren Ambarchi — Salt.

A diagnostic run with direct HTTP and pytest `-x` passed the six new cases and Oren Ambarchi — Salt. It stopped on a MusicBrainz HTTP 503 for Hainbach — BTM Blau. E-3 remains open pending a successful standard live run.

Uncached CLI checks over direct HTTP found Aphex Twin and Warp by name and resolved the MusicBrainz artist, Discogs label, Last.fm artist, and Bandcamp account URLs. The live suite returned the MusicBrainz label ID for Warp. The CLI returned a Discogs identity on a repeat lookup. The control lookup for Burial — Archangel with MusicBrainz, iTunes, Last.fm, and Discogs identified the original track. Discogs review pages returned `blocked`.

**Suggested message:** `test: verify live artist and label lookups`.

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
