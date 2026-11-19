# Requests and the client

An application that looks up many records asks for the data it needs, not for sources, and keeps one client for its whole life. `deadwax.lookup()` remains the one-call form.

## Request

```python
from deadwax import Capability, EntityType, RelationKind, RelationLimit, Request

request = Request(
    query=query,
    facets=frozenset({Capability.TAGS, Capability.RELATIONS, Capability.PREVIEWS}),
    tags_per_source=8,
    relations=(
        RelationLimit(kind=RelationKind.SIMILAR, target=EntityType.RECORDING, per_source=15),
        RelationLimit(kind=RelationKind.SIMILAR, target=EntityType.ARTIST, per_source=8),
        RelationLimit(kind=RelationKind.SIMILAR_ARTIST_RECORDING, per_source=16),
        RelationLimit(kind=RelationKind.MEMBER, per_source=6),
        RelationLimit(kind=RelationKind.ASSOCIATED, per_source=6),
    ),
)
```

| Field | Meaning |
|-------|---------|
| `query` | The record, as for `lookup()` |
| `facets` | Kinds of facts wanted (`Capability`); unset means all of them |
| `tags_per_source` | At most this many tags from each source, in merge order; unset means no cap |
| `relations` | Relation kinds wanted, each with an optional target type and a cap per source; unset means every kind without a cap, an empty tuple means none |

Facets are the adapter capabilities: `identity`, `links`, `previews`, `tags`, `credits`, `texts`, `relations`, `metrics`. `previews` are links with a `preview_url` (iTunes, Spotify, Deezer). On the command line, `--facets tags,previews` sets `Request.facets`.

### Which sources run

The configuration (`default_sources`, `include`, `exclude`) decides which sources *may* run; the request decides which of them are *needed*:

- The identity pass (MusicBrainz) always runs, because later passes rely on its identifiers, and so does the adapter that reads a query URL.
- Other adapters run only when one of their capabilities is among the requested facets other than `identity`. Every adapter that runs still offers a candidate, so the identity is confirmed by all of them through the usual matching gate.
- An adapter may skip requests for facts nobody asked for: `LookupContext.wants(capability)` tells it which facets were requested.

### What the dossier keeps

After the merge the dossier is trimmed to the request. `identity`, `errors`, and `query` are always kept. A facet that was not requested leaves its list empty. With `previews` but not `links`, only links that have a `preview_url` stay. Relations not listed in `relations` are dropped; a listed kind keeps at most `per_source` relations per source, target type, and kind, in merge order. A relation confirmed by several sources counts against the cap of its first source.

## Client

```python
from deadwax import Deadwax, LookupConfig

async with Deadwax(LookupConfig(...)) as client:
    dossier = await client.lookup(request)
    other = await client.lookup(query, include=["core"])
```

`Deadwax` opens the response cache, the per-host rate limiters, and the shared browsers once, and closes them on exit. Lookups may run concurrently: they share the rate limiters, so MusicBrainz is asked at most once a second across all of them. Adapters and their HTTP clients are built for each lookup, so state that belongs to one lookup (access tokens, escalation level, headed browser fallback of a source) does not leak into the next. `client.lookup()` accepts a `Request` or a bare `Query` (all facets), and `include`/`exclude` like `deadwax.lookup()`.

`deadwax.lookup(query_or_request, config, include=..., exclude=..., transport=...)` opens a client for one call.
