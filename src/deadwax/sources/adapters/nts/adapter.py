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
from deadwax.sources.adapters.nts import models, parse


class NtsAdapter(HttpAdapter):
    """Find NTS episodes containing a track and describe their nearby music."""

    name = "nts"
    group = SourceGroup.RADIO
    pass_ = Pass.ENRICH
    service = None
    profile = Profile.API
    capabilities = frozenset({Capability.RELATIONS, Capability.TAGS})

    async def _episode(self, hit: models.Hit, key: RecordKey) -> Partial | None:
        url = parse.episode_url(hit.article)
        if not url or "/shows/" not in url or "/episodes/" not in url:
            return None
        path = url.split("/shows/", 1)[1]
        detail = await self.client.get(f"{parse.API}/shows/{path}")
        episode = models.Episode.model_validate_json(detail.content)
        tracklist = episode.embeds.tracklist.results
        positions = parse.matching_positions(tracklist, key)
        if not positions:
            return None
        matched = tracklist[positions[0]]
        candidate = RecordCandidate(
            kind=EntityKind.TRACK,
            artist=matched.artist or key.artist,
            title=matched.title or key.title,
            url=url,
        )
        source = [Provenance(source=self.name, url=url)]
        date = episode.broadcast or episode.broadcast_date or episode.date
        name = episode.name or hit.article.name or "NTS"
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
        for genre in episode.genres:
            label = genre.value or genre.name
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
        hits = models.Search.model_validate_json(response.content).results
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
