from urllib.parse import unquote_plus, urlsplit

from deadwax.core import (
    ArtistQuery,
    Capability,
    EntityKind,
    IdKind,
    LookupContext,
    Lookups,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordKey,
    Relation,
    Requirement,
    Scope,
    SourceGroup,
    Tag,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._search import name_key, search_key
from deadwax.sources.adapters.lastfm import models
from deadwax.sources.adapters.lastfm import parse as p
from deadwax.sources.services import recognize

API = "https://ws.audioscrobbler.com/2.0/"
SIMILAR_TRACKS = "20"
SIMILAR_ARTISTS = "10"


def _artist_page(url: str | None) -> str | None:
    """Artist page from a track or album page such as '.../music/Artist/_/Track'."""
    if url is None or "/music/" not in url:
        return None
    head, _, rest = url.partition("/music/")
    return f"{head}/music/{rest.split('/', 1)[0]}"


def _key(query: Query, context: LookupContext) -> RecordKey:
    key = search_key(query, context)
    if key is None:
        raise NotFoundError("neither the query nor earlier sources name the record")
    return key


class LastfmAdapter(HttpAdapter):
    """Tags with weights, wiki texts, and similar tracks and artists from Last.fm."""

    name = "lastfm"
    pass_ = Pass.ENRICH
    group = SourceGroup.CORE
    service = "lastfm"
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.TAGS,
            Capability.TEXTS,
            Capability.RELATIONS,
            Capability.METRICS,
        },
    )
    requires = (Requirement(setting="sources.lastfm.api_key", purpose="every lookup"),)
    secret_params = frozenset({"api_key"})

    @property
    def _key(self) -> str | None:
        api_key = self.config.sources.lastfm.api_key
        return api_key.get_secret_value() if api_key is not None else None

    def missing_credential(self) -> str | None:
        """Every Last.fm API call needs a key."""
        return None if self._key else "needs sources.lastfm.api_key"

    async def _call[M: models.ApiModel](self, model: type[M], method: str, **params: str) -> M:
        query = {"method": method, **params, "api_key": self._key or "", "format": "json"}
        response = await self.client.get(API, params=query)
        p.check(response.content, response.url)
        return model.model_validate_json(response.content)

    @property
    def lookups(self) -> Lookups:
        """Tracks, albums, and artists through their own API methods."""
        return Lookups(track=self._find_track, album=self._find_album, artist=self._find_artist)

    def resolves(self, query: Query) -> bool:
        """Whether this is a Last.fm artist profile URL."""
        return (
            isinstance(query, ArtistQuery)
            and query.url is not None
            and super().resolves(query)
            and recognize(query.url)[0] is EntityKind.ARTIST
        )

    async def _find_track(self, query: Query, context: LookupContext) -> Partial:
        return await self._track(_key(query, context), context)

    async def _find_album(self, query: Query, context: LookupContext) -> Partial:
        return await self._album(_key(query, context), context)

    def _artist_params(self, query: ArtistQuery, context: LookupContext) -> dict[str, str]:
        if mbid := context.id(IdKind.MUSICBRAINZ_ARTIST):
            return {"mbid": mbid}
        if query.url is not None and self.resolves(query):
            name = unquote_plus(urlsplit(query.url).path.split("/")[2]).strip()
        else:
            key = name_key(query, context)
            name = key.name if key is not None else ""
        if not name:
            raise NotFoundError("neither the query nor earlier sources name the artist")
        return {"artist": name, "autocorrect": "1"}

    async def _find_artist(self, query: ArtistQuery, context: LookupContext) -> Partial:
        params = self._artist_params(query, context)
        artist = (await self._call(models.ArtistInfoResponse, "artist.getInfo", **params)).artist

        tags = []
        if context.wants(Capability.TAGS):
            tags = await self._artist_tags(artist.name, artist.url)
        relations = []
        if context.wants(Capability.RELATIONS):
            relations = await self._similar_artists(artist.name, artist.url)

        return Partial(
            source=self.name,
            candidate=p.artist_candidate(artist),
            tags=tags,
            texts=p.wiki_texts(artist.bio, Scope.ARTIST, artist.url)
            if context.wants(Capability.TEXTS)
            else [],
            relations=relations,
            metrics=p.artist_metrics(artist) if context.wants(Capability.METRICS) else [],
        )

    async def _artist_tags(self, artist: str, page: str | None) -> list[Tag]:
        found = await self._call(
            models.TopTagsResponse,
            "artist.getTopTags",
            artist=artist,
            autocorrect="1",
        )
        return p.tags(found.toptags.tag, Scope.ARTIST, page, p.ARTIST_TAGS_LIMIT)

    async def _similar_artists(self, artist: str, page: str | None) -> list[Relation]:
        found = await self._call(
            models.SimilarArtistsResponse,
            "artist.getSimilar",
            artist=artist,
            limit=SIMILAR_ARTISTS,
        )
        return p.similar_artists(found.similar.artist, page)

    async def _track(self, key: RecordKey, context: LookupContext) -> Partial:
        names = {"artist": key.artist, "track": key.title, "autocorrect": "1"}
        track = (await self._call(models.TrackInfoResponse, "track.getInfo", **names)).track

        names = {"artist": track.artist.name, "track": track.name}
        artist_page = track.artist.url or _artist_page(track.url)
        tags: list[Tag] = []
        if context.wants(Capability.TAGS):
            top = await self._call(models.TopTagsResponse, "track.getTopTags", **names)
            tags = p.tags(top.toptags.tag, Scope.RECORDING, track.url)
            tags += await self._artist_tags(track.artist.name, artist_page)
        relations: list[Relation] = []
        if context.wants(Capability.RELATIONS):
            similar = await self._call(
                models.SimilarTracksResponse,
                "track.getSimilar",
                **names,
                limit=SIMILAR_TRACKS,
            )
            relations = p.similar_tracks(similar.similartracks.track, track.url)
            relations += await self._similar_artists(track.artist.name, artist_page)

        return Partial(
            source=self.name,
            candidate=p.track_candidate(track),
            tags=tags,
            texts=p.wiki_texts(track.wiki, Scope.RECORDING, track.url),
            relations=relations,
        )

    async def _album(self, key: RecordKey, context: LookupContext) -> Partial:
        names = {"artist": key.artist, "album": key.title, "autocorrect": "1"}
        album = (await self._call(models.AlbumInfoResponse, "album.getInfo", **names)).album

        names = {"artist": album.artist, "album": album.name}
        artist_page = _artist_page(album.url)
        tags: list[Tag] = []
        if context.wants(Capability.TAGS):
            top = await self._call(models.TopTagsResponse, "album.getTopTags", **names)
            tags = p.tags(top.toptags.tag, Scope.RELEASE_GROUP, album.url)
            tags += await self._artist_tags(album.artist, artist_page)
        relations: list[Relation] = []
        if context.wants(Capability.RELATIONS):
            relations = await self._similar_artists(album.artist, artist_page)

        return Partial(
            source=self.name,
            candidate=p.album_candidate(album),
            tags=tags,
            texts=p.wiki_texts(album.wiki, Scope.RELEASE_GROUP, album.url),
            relations=relations,
        )
