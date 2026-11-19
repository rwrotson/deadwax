import json
from collections.abc import Mapping

from deadwax.core import (
    AdapterError,
    BlockedError,
    Capability,
    Credit,
    Entity,
    EntityKind,
    EntityType,
    ErrorKind,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RecordKey,
    Relation,
    RelationKind,
    Requirement,
    Scope,
    SourceError,
    SourceGroup,
    Text,
    TextKind,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import ClientSpec, HttpClient, HttpResources, Profile
from deadwax.sources._search import SearchHit, pick_hit, search_key
from deadwax.sources.adapters.genius import parse
from deadwax.sources.config import SourcesConfig


class GeniusAdapter(HttpAdapter):
    """Song descriptions, annotations, credits, relations, and lyrics from Genius."""

    name = "genius"
    pass_ = Pass.ENRICH
    group = SourceGroup.CATALOGUES
    additional_profiles = (Profile.BROWSER,)
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.TEXTS,
            Capability.CREDITS,
            Capability.RELATIONS,
            Capability.LINKS,
        },
    )
    requires = (Requirement(setting="genius.token", purpose="every lookup"),)

    def __init__(self, config: SourcesConfig, resources: HttpResources) -> None:
        super().__init__(config, resources)
        self._page_client: HttpClient | None = None

    def missing_credential(self) -> str | None:
        """Report when the API token is unavailable."""
        return "genius.token" if self.config.genius.token is None else None

    def headers(self) -> Mapping[str, str]:
        """Authorize API calls with the configured token."""
        token = self.config.genius.token
        return {"authorization": f"Bearer {token.get_secret_value()}"} if token else {}

    @property
    def page_client(self) -> HttpClient:
        """Fetch public song HTML without sending the API token."""
        if self._page_client is None:
            self._page_client = HttpClient(
                ClientSpec(self.name, Profile.BROWSER, {}, frozenset(), None),
                self.config,
                self.resources,
            )
        return self._page_client

    async def aclose(self) -> None:
        """Close API and HTML transports."""
        await super().aclose()
        if self._page_client is not None:
            await self._page_client.aclose()
            self._page_client = None

    async def _get(self, path: str, **params: str) -> Mapping[str, object]:
        response = await self.client.get(f"{parse.API}{path}", params=params or None)
        payload = json.loads(response.content)
        return parse.as_song(parse.as_song(payload).get("response"))

    async def _find(self, key: RecordKey) -> int:
        results = await self._get("/search", q=f"{key.artist} {key.title}")
        hits: list[SearchHit] = []
        ids: dict[str, int] = {}
        for item in parse.as_list(results.get("hits")):
            song = parse.as_song(parse.as_song(item).get("result"))
            candidate = parse.candidate(song)
            song_id = song.get("id")
            if candidate is not None and isinstance(song_id, int) and candidate.url:
                hits.append(
                    SearchHit(
                        key=RecordKey(
                            artist=candidate.artist,
                            title=candidate.title,
                            kind=EntityKind.TRACK,
                        ),
                        url=candidate.url,
                    ),
                )
                ids[candidate.url] = song_id
        hit = pick_hit(key, hits)
        if hit is None:
            raise NotFoundError("no matching Genius song")
        return ids[hit.url]

    async def _annotations(self, song_id: int, url: str) -> list[Text]:
        texts: list[Text] = []
        page = 1
        while page <= parse.MAX_ANNOTATION_PAGES:
            referents = await self._get(
                "/referents",
                song_id=str(song_id),
                page=str(page),
                per_page="20",
                text_format="plain",
            )
            for referent in parse.as_list(referents.get("referents")):
                for annotation in parse.as_list(parse.as_song(referent).get("annotations")):
                    note = parse.as_song(annotation)
                    body = parse.plain_text(note.get("body"))
                    if body:
                        note_url = note.get("url")
                        note_source = [
                            Provenance(
                                source=self.name,
                                url=note_url if isinstance(note_url, str) else url,
                            ),
                        ]
                        texts.append(
                            Text(
                                kind=TextKind.USER,
                                body=body,
                                scope=Scope.WORK,
                                sources=note_source,
                            ),
                        )
            if not referents.get("next_page"):
                break
            page += 1
        return texts

    def _relations(self, song: Mapping[str, object], source: list[Provenance]) -> list[Relation]:
        relations: list[Relation] = []
        kinds = {
            "samples": RelationKind.SAMPLES,
            "sampled_in": RelationKind.SAMPLED_BY,
            "cover_of": RelationKind.COVER_OF,
            "covered_by": RelationKind.COVERED_BY,
            "remix_of": RelationKind.REMIX_OF,
            "remixed_by": RelationKind.REMIXED_BY,
            "interpolates": RelationKind.INTERPOLATES,
            "interpolated_by": RelationKind.INTERPOLATED_BY,
        }
        for relationship in parse.as_list(song.get("song_relationships")):
            data = parse.as_song(relationship)
            relationship_type = data.get("relationship_type")
            kind = kinds.get(relationship_type) if isinstance(relationship_type, str) else None
            if kind is None:
                continue
            for item in parse.as_list(data.get("songs")):
                related = parse.as_song(item)
                title = related.get("title")
                if isinstance(title, str):
                    relations.append(
                        Relation(
                            kind=kind,
                            target=Entity(
                                type=EntityType.RECORDING,
                                name=title,
                                artist=parse.name_of(related.get("primary_artist")) or None,
                                url=parse.url_of(related) or None,
                            ),
                            scope=Scope.WORK,
                            sources=source,
                        ),
                    )
        return relations

    def _credits(self, song: Mapping[str, object], source: list[Provenance]) -> list[Credit]:
        found: list[Credit] = []
        for field, role in (("writer_artists", "writer"), ("producer_artists", "producer")):
            for item in parse.as_list(song.get(field)):
                name = parse.name_of(item)
                if name:
                    found.append(Credit(role=role, name=name, scope=Scope.WORK, sources=source))
        return found

    async def _page_lyrics(
        self,
        url: str,
        source: list[Provenance],
    ) -> tuple[list[Text], list[AdapterError]]:
        try:
            body = parse.lyrics((await self.page_client.get(url)).content)
        except (BlockedError, SourceError) as error:
            return [], [
                AdapterError(
                    source=self.name,
                    kind=ErrorKind.BLOCKED if isinstance(error, BlockedError) else ErrorKind.FAILED,
                    reason=str(error),
                    url=url,
                ),
            ]
        if body:
            return [Text(kind=TextKind.LYRICS, body=body, scope=Scope.WORK, sources=source)], []
        return [], []

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Find a matching song and collect its API data and page lyrics."""
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        if key.kind is EntityKind.ALBUM:
            return Partial(source=self.name)
        song_id = await self._find(key)
        song = parse.as_song((await self._get(f"/songs/{song_id}")).get("song"))
        candidate = parse.candidate(song)
        if candidate is None:
            raise SourceError("Genius returned a song without artist or title")
        url = parse.url_of(song)
        source = [Provenance(source=self.name, url=url)]
        texts: list[Text] = []
        description = parse.plain_text(song.get("description"))
        if description:
            texts.append(
                Text(kind=TextKind.EDITORIAL, body=description, scope=Scope.WORK, sources=source),
            )
        texts.extend(await self._annotations(song_id, url))
        lyrics: list[Text] = []
        errors: list[AdapterError] = []
        if url:
            lyrics, errors = await self._page_lyrics(url, source)
        texts.extend(lyrics)
        return Partial(
            source=self.name,
            candidate=candidate,
            texts=texts,
            relations=self._relations(song, source),
            credits=self._credits(song, source),
            links=[Link(service=self.name, url=url, target=LinkTarget.TRACK, sources=source)]
            if url
            else [],
            errors=errors,
        )
