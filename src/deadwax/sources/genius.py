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
    RecordCandidate,
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
from deadwax.sources._base import HttpAdapter, SearchHit, pick_hit, search_key
from deadwax.sources._html import parse_html
from deadwax.sources._http import ClientSpec, HttpClient, HttpResources, Profile
from deadwax.sources.config import SourcesConfig

API = "https://api.genius.com"
MAX_ANNOTATION_PAGES = 3


def _plain(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    plain = value.get("plain")
    return plain.strip() if isinstance(plain, str) else ""


def _song(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _name(value: object) -> str:
    name = _song(value).get("name")
    return name if isinstance(name, str) else ""


def _url(song: Mapping[str, object]) -> str:
    value = song.get("url")
    return value if isinstance(value, str) else ""


def _candidate(song: Mapping[str, object]) -> RecordCandidate | None:
    title = song.get("title")
    artist = _name(song.get("primary_artist"))
    if not isinstance(title, str) or not artist:
        return None
    return RecordCandidate(kind=EntityKind.TRACK, artist=artist, title=title, url=_url(song))


def _lyrics(content: bytes) -> str:
    tree = parse_html(content)
    containers = tree.css('[data-lyrics-container="true"]')
    lines = [container.text(separator="\n", strip=True) for container in containers]
    return "\n".join(line for line in lines if line).strip()


class GeniusAdapter(HttpAdapter):
    """Song descriptions, annotations, credits, relations, and lyrics from Genius."""

    name = "genius"
    pass_ = Pass.ENRICH
    group = SourceGroup.CATALOGUES
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
        response = await self.client.get(f"{API}{path}", params=params or None)
        payload = json.loads(response.content)
        return _song(_song(payload).get("response"))

    async def _find(self, key: RecordKey) -> int:
        results = await self._get("/search", q=f"{key.artist} {key.title}")
        hits: list[SearchHit] = []
        ids: dict[str, int] = {}
        for item in _items(results.get("hits")):
            song = _song(_song(item).get("result"))
            candidate = _candidate(song)
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
        while page <= MAX_ANNOTATION_PAGES:
            referents = await self._get(
                "/referents",
                song_id=str(song_id),
                page=str(page),
                per_page="20",
                text_format="plain",
            )
            for referent in _items(referents.get("referents")):
                for annotation in _items(_song(referent).get("annotations")):
                    note = _song(annotation)
                    body = _plain(note.get("body"))
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
        for relationship in _items(song.get("song_relationships")):
            data = _song(relationship)
            relationship_type = data.get("relationship_type")
            kind = kinds.get(relationship_type) if isinstance(relationship_type, str) else None
            if kind is None:
                continue
            for item in _items(data.get("songs")):
                related = _song(item)
                title = related.get("title")
                if isinstance(title, str):
                    relations.append(
                        Relation(
                            kind=kind,
                            target=Entity(
                                type=EntityType.RECORDING,
                                name=title,
                                artist=_name(related.get("primary_artist")) or None,
                                url=_url(related) or None,
                            ),
                            scope=Scope.WORK,
                            sources=source,
                        ),
                    )
        return relations

    def _credits(self, song: Mapping[str, object], source: list[Provenance]) -> list[Credit]:
        found: list[Credit] = []
        for field, role in (("writer_artists", "writer"), ("producer_artists", "producer")):
            for item in _items(song.get(field)):
                name = _name(item)
                if name:
                    found.append(Credit(role=role, name=name, scope=Scope.WORK, sources=source))
        return found

    async def _page_lyrics(
        self,
        url: str,
        source: list[Provenance],
    ) -> tuple[list[Text], list[AdapterError]]:
        try:
            body = _lyrics((await self.page_client.get(url)).content)
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
        song = _song((await self._get(f"/songs/{song_id}")).get("song"))
        candidate = _candidate(song)
        if candidate is None:
            raise SourceError("Genius returned a song without artist or title")
        url = _url(song)
        source = [Provenance(source=self.name, url=url)]
        texts: list[Text] = []
        description = _plain(song.get("description"))
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
