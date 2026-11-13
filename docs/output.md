# Output

A lookup returns a `Dossier`. `deadwax --format json` prints it as JSON (`Dossier.model_dump_json()`), `--format markdown` through `to_markdown()`, and `--format pretty` as rich sections in the terminal. The JSON Schema is on the [Schema](schema.md) page.

## Provenance

Every fact has `sources`: a list of `Provenance(source, url)`, where `source` is the adapter name (`musicbrainz`, `discogs`, …) and `url` the page or API resource the fact was read from. When several sources give the same fact, it appears once with all of them. Nothing is inferred: a field no source filled stays empty (`null` or `[]`).

## Identity

`identity` describes the exact record that was found:

| Field | Content |
|-------|---------|
| `kind` | `track` or `album` |
| `artist`, `title`, `date` | Sourced values: `{"value": …, "sources": […]}`; `date` is an ISO date, possibly partial (`1997`, `1997-05`) |
| `version` | `kind` (`original`, `remix`, `live`, `demo`, `cover`, `instrumental`, `acoustic`, `edit`, `alternate`, `reissue`, `remaster`) and `detail`, the marker it came from (`Todd Terry Remix`) |
| `labels` | Label name and catalog number, with sources |
| `isrcs`, `upcs` | Sourced codes |
| `external_ids` | IDs in other namespaces: MusicBrainz, Discogs, Wikidata, Bandcamp, Spotify, Apple Music, Deezer |
| `discrepancies` | Fields on which sources disagree, each with every value and its sources |

Candidates are compared with the query text, or for a URL query with the URL's own page. Among accepted candidates, the value given by the most sources becomes the identity, and every disagreement on artist, title, version, date, or an ID is kept in `discrepancies` instead of being resolved silently.

### Versions are never mixed

Each source's candidate is compared with the query by artist and base title, and its version separately. A candidate for the same work in another version (the original of a remix, a live take, a remaster) contributes none of its facts. It becomes a relation of kind `other_version`, with the version in `note`, and a `version` discrepancy. A candidate that matches neither becomes an error of kind `no_match`. Album and track never match each other, and a title alone never matches.

## Facts

Facts have a `scope`: `recording`, `work`, `release`, `release_group`, `artist`, or `label`. Lists are ordered with the narrowest scope for the queried kind first, so facts about this recording or release come before artist-wide ones.

| List | Item fields |
|------|-------------|
| `tags` | `name`, `kind` (`genre`, `style`, `mood`, `theme`, `descriptor`, `tag`), `weight` (0–1, the source's own weighting, when it has one) |
| `credits` | `role`, `name`, `detail` (instruments or tracks the credit covers) |
| `texts` | `kind` (`review`, `editorial`, `label`, `shop`, `wiki`, `user`, `broadcast`), `body`, `title`, `author`, `publication`, `date`, `rating` (`value`, `scale`, `text`), `language` |
| `relations` | `kind`, `target` (`type`, `name`, `artist`, `date`, `url`, `ids`), `note` |
| `metrics` | `kind` (`listens`, `listeners`), `value`, `scale` (highest possible value, when bounded) |
| `links` | `service`, `url`, `target` (`track`, `album`, `artist`, `label`, `other`), `preview_url` |

A `broadcast` text is a radio host's note on a play, with the host as `author` and the station and program as `publication`. Metrics are counts one source reports; they are never combined across sources.

Relations to the same target from several sources merge into one, with every source, and the merged target keeps the artist, date, URL, and IDs any of them gave. Broadcasts and mixes are also told apart by date.

A score without review text (a ratings template on Wikipedia, a Wikidata review score) is a `review` text with an empty `body`, a `publication`, and a `rating`.

Relation kinds are directional:

| Kind | Target |
|------|--------|
| `member`, `project` | Band members; other projects of the artist or its members |
| `label`, `label_release` | The label; its other releases |
| `appears_on`, `compilation` | Releases and compilations containing the record |
| `mix`, `broadcast` | DJ mixes and broadcasts containing it |
| `cover_of`, `covered_by` | The original it covers; covers of it |
| `remix_of`, `remixed_by` | The original it remixes; remixes of it |
| `samples`, `sampled_by` | What it samples; what samples it |
| `similar` | Similar records or artists according to a source |
| `other_version` | Another version of the same work, kept apart from the identity |

## Errors

`errors` lists sources that contributed nothing or only part of what they could. Each has `source`, `kind`, `reason`, and sometimes `url`:

| Kind | Meaning |
|------|---------|
| `skipped` | A required setting or extra is missing, or nothing earlier in the lookup gave the source a way in |
| `failed` | Unexpected response or exception (logged with its traceback) |
| `timeout` | The source exceeded `adapter_timeout` (`--timeout`) |
| `blocked` | Bot protection refused the page after the escalation ladder; `(cached)` when the refusal is remembered from an earlier run |
| `rate_limited` | The source kept answering 429 beyond `http.max_retry_wait` |
| `not_found` | The source has no such record |
| `no_match` | The source found something, but not this record |

Sources excluded with `--exclude`, left out of `--sources` or of the default set, or disabled in settings produce no error. A failing source never stops the others and never raises out of `lookup()`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | A source identified the record (`identity.title` is set) |
| 1 | Unexpected error |
| 2 | Usage or configuration error |
| 3 | Nothing matched the query |
