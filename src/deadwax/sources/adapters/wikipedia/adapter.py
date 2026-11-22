from collections.abc import Iterable

from deadwax.core import (
    ArtistQuery,
    Capability,
    EntityKind,
    IdKind,
    LabelQuery,
    LookupContext,
    Lookups,
    NameKey,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordKey,
    Scope,
    SourceGroup,
    Text,
    normalize_text,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._search import name_key, search_key
from deadwax.sources.adapters.wikipedia import models
from deadwax.sources.adapters.wikipedia import parse as p

WIKIDATA_API = f"{p.WIKIDATA}/w/api.php"
SEARCH_LIMIT = "5"
_NAME_PROPS = "labels|aliases|claims|sitelinks"

# wbgetentities accepts at most 50 IDs per request.
_BATCH = 50


class WikipediaAdapter(HttpAdapter):
    """Genres, credits, review scores, and article sections from Wikidata and Wikipedia."""

    name = "wikipedia"
    pass_ = Pass.ENRICH
    group = SourceGroup.CORE
    service = None
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.TAGS,
            Capability.CREDITS,
            Capability.TEXTS,
            Capability.RELATIONS,
        },
    )

    async def _api[M: models.ApiModel](self, model: type[M], url: str, **params: str) -> M:
        response = await self.client.get(url, params={**params, "format": "json"})
        p.check(response.content, response.url)
        return model.model_validate_json(response.content)

    async def _entities(
        self,
        ids: Iterable[str],
        props: str,
        languages: Iterable[str] = (),
    ) -> dict[str, models.Item]:
        wanted = list(dict.fromkeys(ids))
        extra = {"languages": "|".join(languages)} if languages else {}
        found: dict[str, models.Item] = {}
        for start in range(0, len(wanted), _BATCH):
            batch = "|".join(wanted[start : start + _BATCH])
            response = await self._api(
                models.Entities,
                WIKIDATA_API,
                action="wbgetentities",
                ids=batch,
                props=props,
                **extra,
            )
            found |= response.entities
        return found

    @property
    def lookups(self) -> Lookups:
        """Tracks, albums, artists, and labels."""
        return Lookups(
            track=self.find,
            album=self.find,
            artist=self.find_name,
            label=self.find_name,
            unresolved=self.find,
        )

    async def find(self, query: Query, context: LookupContext) -> Partial:
        """Read the Wikidata item from earlier passes or a search, then its articles."""
        key = search_key(query, context)
        qid = context.id(IdKind.WIKIDATA)
        if qid is None:
            if key is None:
                raise NotFoundError("neither the query nor earlier sources name the record")
            qid = await self._search(key)

        item = (await self._entities([qid], "labels|claims|sitelinks")).get(qid)
        if item is None or not item.claims:
            raise NotFoundError("no such Wikidata item", url=p.entity_url(qid))
        kind = (key.kind if key is not None else None) or (
            EntityKind.ALBUM if p.fits(item, EntityKind.ALBUM) else EntityKind.TRACK
        )

        original = await self._original_language(item)
        referenced = await self._entities(
            p.referenced(item),
            "labels|aliases",
            p.languages(original),
        )
        labels = p.Labels(referenced, original)

        parts = await self._entities(item.items(p.PART_OF), "claims")
        albums = {qid for qid, part in parts.items() if p.fits(part, EntityKind.ALBUM)}

        scope = Scope.RELEASE_GROUP if kind is EntityKind.ALBUM else Scope.RECORDING
        artist = key.artist if key is not None else None
        candidate = p.candidate(item, kind, labels, original, artist)
        texts = await self._articles(item, original, scope)
        known = {normalize_text(t.publication) for t in texts if t.publication and t.rating}

        return Partial(
            source=self.name,
            candidate=candidate,
            tags=p.claim_tags(item, labels, scope),
            credits=p.claim_credits(item, labels, scope),
            texts=texts + p.claim_ratings(item, labels, scope, known),
            relations=p.claim_relations(item, labels, scope, albums),
        )

    async def _search_ids(self, search: str) -> list[str]:
        found = await self._api(
            models.Search,
            WIKIDATA_API,
            action="query",
            list="search",
            srsearch=search,
            srlimit=SEARCH_LIMIT,
        )
        return [hit.title for hit in found.query.search]

    async def _search(self, key: RecordKey) -> str:
        """Find the item of the record by its title, type, and performer."""
        language = p.search_language(f"{key.artist} {key.title}")
        type_filter = f" {p.type_filter(key.kind)}" if key.kind is not None else ""
        ids = await self._search_ids(f"{key.title}{type_filter}")
        if not ids:
            raise NotFoundError("no Wikidata item with this title")

        items = await self._entities(ids, "labels|aliases|claims", p.languages(language))
        ordered = [items[qid] for qid in ids if qid in items]
        performers = await self._entities(
            (qid for item in ordered for qid in item.items(p.PERFORMER)),
            "labels|aliases",
            p.languages(language),
        )

        qid = p.pick(key, ordered, performers, language)
        if qid is None:
            raise NotFoundError("no matching Wikidata item")
        return qid

    async def find_name(self, query: ArtistQuery | LabelQuery, context: LookupContext) -> Partial:
        """Find the artist or label and read its claims and articles."""
        key = name_key(query, context)
        kind = query.kind
        language = p.search_language(key.name) if key is not None else "en"
        known_ids = {
            id_kind: value
            for id_kind in p.NAME_IDS[kind].values()
            if (value := context.id(id_kind)) is not None
        }
        qid = context.id(IdKind.WIKIDATA)
        if qid is not None:
            items = await self._entities([qid], _NAME_PROPS)
            item = items.get(qid)
            if item is None or not item.labels:
                raise NotFoundError("no such Wikidata item", url=p.entity_url(qid))
        else:
            item = await self._search_name(kind, key, known_ids, language)

        original = await self._original_language(item) or language
        referenced = await self._entities(
            p.name_references(item, kind),
            "labels",
            p.languages(original),
        )
        labels = p.Labels(referenced, original)
        scope = Scope.ARTIST if kind is EntityKind.ARTIST else Scope.LABEL
        return Partial(
            source=self.name,
            candidate=p.name_candidate(item, kind, labels, key, known_ids),
            tags=p.claim_tags(item, labels, scope),
            relations=p.name_relations(item, kind, labels, scope),
            texts=await self._articles(item, original, scope)
            if context.wants(Capability.TEXTS)
            else [],
        )

    async def _search_name(
        self,
        kind: EntityKind,
        key: NameKey | None,
        known_ids: dict[IdKind, str],
        language: str,
    ) -> models.Item:
        properties = p.NAME_IDS[kind]
        for prop, id_kind in properties.items():
            if (value := known_ids.get(id_kind)) is None:
                continue
            ids = await self._search_ids(f"haswbstatement:{prop}={value}")
            items = await self._entities(ids, _NAME_PROPS)
            for qid in ids:
                if (item := items.get(qid)) is not None and value in item.texts(prop):
                    return item

        if not known_ids and key is not None:
            prop = next(iter(properties))
            ids = await self._search_ids(f"{key.name} haswbstatement:{prop}")
            items = await self._entities(ids, _NAME_PROPS)
            item = p.pick_name(key, [items[qid] for qid in ids if qid in items], language)
            if item is not None:
                return item

        raise NotFoundError("no matching Wikidata item for the artist or label")

    async def _original_language(self, item: models.Item) -> str | None:
        """Wiki language code of the record's language, if the item states it."""
        language_items = item.items(p.LANGUAGE)
        if not language_items:
            return None
        claims = await self._api(
            models.Claims,
            WIKIDATA_API,
            action="wbgetclaims",
            entity=language_items[0],
            property=p.WIKI_LANGUAGE_CODE,
        )
        return p.wiki_code(claims)

    async def _articles(self, item: models.Item, original: str | None, scope: Scope) -> list[Text]:
        """Sections and ratings of the English and original-language articles."""
        texts: list[Text] = []
        records = scope not in {Scope.ARTIST, Scope.LABEL}
        for language in dict.fromkeys(lang for lang in (original, "en") if lang):
            sitelink = item.sitelinks.get(f"{language}wiki")
            if sitelink is None:
                continue
            try:
                page = await self._api(
                    models.Parse,
                    f"https://{language}.wikipedia.org/w/api.php",
                    action="parse",
                    page=sitelink.title,
                    prop="text|wikitext" if records else "text",
                    formatversion="2",
                    redirects="1",
                    disableeditsection="1",
                    disabletoc="1",
                )
            except NotFoundError:
                continue
            # A sitelink that redirects leads to an article about something else, such as
            # a song's link to its album.
            if page.parse.title != sitelink.title:
                continue
            url = p.article_url(language, page.parse.title)
            texts += p.sections(page.parse.text, page.parse.title, language, scope, url)
            if records:
                texts += p.ratings(page.parse.wikitext, language, scope, url)

        return texts
