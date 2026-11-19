from deadwax.core import (
    Capability,
    EntityKind,
    IdKind,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordKey,
    SourceGroup,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._search import search_key
from deadwax.sources.adapters.itunes import parse
from deadwax.sources.adapters.itunes.models import Item, Results


class ItunesAdapter(HttpAdapter):
    """Apple Music links and previews from the keyless iTunes Search API."""

    name = parse.SOURCE
    pass_ = Pass.ENRICH
    group = SourceGroup.CORE
    service = "apple_music"
    capabilities = frozenset(
        {Capability.IDENTITY, Capability.LINKS, Capability.PREVIEWS, Capability.TAGS},
    )

    def resolves(self, query: Query) -> bool:
        """Apple Music URLs."""
        return IdKind.APPLE_MUSIC in query.ids

    async def _get(self, path: str, **params: str) -> list[Item]:
        response = await self.client.get(f"{parse.API}{path}", params=params)
        return Results.model_validate_json(response.content).results

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Look up the Apple Music ID of the query, or search by artist and title."""
        apple_id = query.ids.get(IdKind.APPLE_MUSIC) or parse.linked_id(query, context)
        if apple_id is not None:
            items = [item for item in await self._get("lookup", id=apple_id) if item.kind]
            if not items:
                raise NotFoundError(f"no iTunes item {apple_id}")
            return parse.partial(items[0])

        reference = search_key(query, context)
        if reference is None:
            raise NotFoundError("neither the query nor earlier sources name the record")

        kind = reference.kind or EntityKind.TRACK
        entity = "song" if kind is EntityKind.TRACK else "album"
        items = await self._get(
            "search",
            term=f"{reference.artist} {reference.title}",
            media="music",
            entity=entity,
            limit=parse.SEARCH_LIMIT,
        )

        item = parse.pick(
            RecordKey(reference.artist, reference.title, kind, reference.version),
            items,
        )
        if item is None:
            raise NotFoundError("no matching iTunes item")
        return parse.partial(item)
