import json
from urllib.parse import urljoin

from deadwax.core import (
    Capability,
    Entity,
    EntityKind,
    EntityType,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    SourceGroup,
    Tag,
    TagKind,
    Verdict,
    compare,
)
from deadwax.sources._base import HttpAdapter, search_key
from deadwax.sources._http import Profile

API = "https://www.nts.live/api/v2"


def _object(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _items(value: object) -> list[dict[str, object]]:
    return [_object(item) for item in value] if isinstance(value, list) else []


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _episode_url(item: dict[str, object]) -> str | None:
    value = _string(item.get("url")) or _string(item.get("path"))
    return urljoin("https://www.nts.live", value) if value else None


def _matching_positions(tracklist: list[dict[str, object]], key: RecordKey) -> list[int]:
    return [
        index
        for index, track in enumerate(tracklist)
        if compare(
            key,
            RecordKey(
                artist=_string(track.get("artist")) or "",
                title=_string(track.get("title")) or "",
                kind=EntityKind.TRACK,
            ),
        ).verdict
        is Verdict.MATCH
    ]


def _neighbours(
    tracklist: list[dict[str, object]],
    positions: list[int],
    source: list[Provenance],
) -> list[Relation]:
    result = []
    for position in positions:
        for neighbour in (position - 1, position + 1):
            if not 0 <= neighbour < len(tracklist):
                continue
            track = tracklist[neighbour]
            title = _string(track.get("title"))
            if not title:
                continue
            result.append(
                Relation(
                    kind=RelationKind.CO_PLAYED,
                    target=Entity(
                        type=EntityType.RECORDING,
                        name=title,
                        artist=_string(track.get("artist")),
                    ),
                    note="before" if neighbour < position else "after",
                    scope=Scope.RECORDING,
                    sources=source,
                ),
            )
    return result


class NtsAdapter(HttpAdapter):
    """Find NTS episodes containing a track and describe their nearby music."""

    name = "nts"
    group = SourceGroup.RADIO
    pass_ = Pass.ENRICH
    profile = Profile.API
    capabilities = frozenset({Capability.RELATIONS, Capability.TAGS})

    async def _episode(self, hit: dict[str, object], key: RecordKey) -> Partial | None:
        episode = _object(hit.get("episode")) or hit
        url = _episode_url(episode)
        if not url or "/shows/" not in url or "/episodes/" not in url:
            return None
        path = url.split("/shows/", 1)[1]
        detail = await self.client.get(f"{API}/shows/{path}")
        data = _object(json.loads(detail.content))
        tracklist = _items(_object(_object(data.get("embeds")).get("tracklist")).get("results"))
        positions = _matching_positions(tracklist, key)
        if not positions:
            return None
        matched = tracklist[positions[0]]
        candidate = RecordCandidate(
            kind=EntityKind.TRACK,
            artist=_string(matched.get("artist")) or key.artist,
            title=_string(matched.get("title")) or key.title,
            url=url,
        )
        source = [Provenance(source=self.name, url=url)]
        date = (
            _string(data.get("broadcast"))
            or _string(data.get("broadcast_date"))
            or _string(data.get("date"))
        )
        name = _string(data.get("name")) or _string(episode.get("name")) or "NTS"
        relations: list[Relation] = []
        tags: list[Tag] = []
        relations.append(
            Relation(
                kind=RelationKind.BROADCAST,
                target=Entity(
                    type=EntityType.BROADCAST,
                    name=f"NTS: {name}",
                    date=date[:10] if date else None,
                    url=url,
                ),
                scope=Scope.RECORDING,
                sources=source,
            ),
        )
        relations.extend(_neighbours(tracklist, positions, source))
        for genre in _items(data.get("genres")):
            label = _string(genre.get("value")) or _string(genre.get("name"))
            if label:
                tags.append(
                    Tag(
                        name=label,
                        kind=TagKind.GENRE,
                        context_url=url,
                        scope=Scope.RECORDING,
                        sources=source,
                    ),
                )
        return Partial(source=self.name, candidate=candidate, relations=relations, tags=tags)

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Search the public track index, then verify each episode tracklist."""
        key = search_key(query, context)
        if key is None or key.kind is EntityKind.ALBUM:
            raise NotFoundError("NTS track search needs an artist and track title")
        response = await self.client.get(
            f"{API}/search",
            params={"q": f"{key.artist} {key.title}", "type": "track"},
        )
        hits = _items(_object(json.loads(response.content)).get("results"))
        partials = [p for hit in hits[:20] if (p := await self._episode(hit, key)) is not None]
        if not partials:
            raise NotFoundError("no NTS episode with this recording", url=response.url)
        return Partial(
            source=self.name,
            candidate=partials[0].candidate,
            relations=[relation for partial in partials for relation in partial.relations],
            tags=[tag for partial in partials for tag in partial.tags],
        )
