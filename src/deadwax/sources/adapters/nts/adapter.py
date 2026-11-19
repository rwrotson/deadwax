import json

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
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import Profile
from deadwax.sources._search import search_key
from deadwax.sources.adapters.nts import parse


class NtsAdapter(HttpAdapter):
    """Find NTS episodes containing a track and describe their nearby music."""

    name = "nts"
    group = SourceGroup.RADIO
    pass_ = Pass.ENRICH
    profile = Profile.API
    capabilities = frozenset({Capability.RELATIONS, Capability.TAGS})

    async def _episode(self, hit: dict[str, object], key: RecordKey) -> Partial | None:
        episode = parse.as_object(hit.get("article"))
        url = parse.episode_url(episode)
        if not url or "/shows/" not in url or "/episodes/" not in url:
            return None
        path = url.split("/shows/", 1)[1]
        detail = await self.client.get(f"{parse.API}/shows/{path}")
        data = parse.as_object(json.loads(detail.content))
        tracklist = parse.as_objects(
            parse.as_object(parse.as_object(data.get("embeds")).get("tracklist")).get("results"),
        )
        positions = parse.matching_positions(tracklist, key)
        if not positions:
            return None
        matched = tracklist[positions[0]]
        candidate = RecordCandidate(
            kind=EntityKind.TRACK,
            artist=parse.as_text(matched.get("artist")) or key.artist,
            title=parse.as_text(matched.get("title")) or key.title,
            url=url,
        )
        source = [Provenance(source=self.name, url=url)]
        date = (
            parse.as_text(data.get("broadcast"))
            or parse.as_text(data.get("broadcast_date"))
            or parse.as_text(data.get("date"))
        )
        name = parse.as_text(data.get("name")) or parse.as_text(episode.get("name")) or "NTS"
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
        relations.extend(parse.neighbours(tracklist, positions, source))
        for genre in parse.as_objects(data.get("genres")):
            label = parse.as_text(genre.get("value")) or parse.as_text(genre.get("name"))
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
            f"{parse.API}/search",
            params={
                "q": f"{key.artist} {key.title}",
                "version": "2",
                "offset": "0",
                "limit": "36",
                "types[]": "track",
            },
        )
        hits = parse.as_objects(parse.as_object(json.loads(response.content)).get("results"))
        matching = [hit for hit in hits if parse.hit_matches(hit, key)]
        partials = [p for hit in matching[:10] if (p := await self._episode(hit, key)) is not None]
        if not partials:
            raise NotFoundError("no NTS episode with this recording", url=response.url)
        return Partial(
            source=self.name,
            candidate=partials[0].candidate,
            relations=[relation for partial in partials for relation in partial.relations],
            tags=[tag for partial in partials for tag in partial.tags],
        )
