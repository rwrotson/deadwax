from deadwax.core import (
    Capability,
    EntityKind,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RecordKey,
    Requirement,
    Scope,
    Tag,
)
from deadwax.sources._base import HttpAdapter, search_key
from deadwax.sources.lastfm import models
from deadwax.sources.lastfm import parse as p

API = "https://ws.audioscrobbler.com/2.0/"
SIMILAR_TRACKS = "20"
SIMILAR_ARTISTS = "10"


def _artist_page(url: str | None) -> str | None:
    """Artist page from a track or album page such as '.../music/Artist/_/Track'."""
    if url is None or "/music/" not in url:
        return None
    head, _, rest = url.partition("/music/")
    return f"{head}/music/{rest.split('/', 1)[0]}"


class LastfmAdapter(HttpAdapter):
    """Tags with weights, wiki texts, and similar tracks and artists from Last.fm."""

    name = "lastfm"
    pass_ = Pass.ENRICH
    capabilities = frozenset(
        {Capability.IDENTITY, Capability.TAGS, Capability.TEXTS, Capability.RELATIONS},
    )
    requires = (Requirement(setting="lastfm.api_key", purpose="every lookup"),)
    secret_params = frozenset({"api_key"})

    @property
    def _key(self) -> str | None:
        api_key = self.config.lastfm.api_key
        return api_key.get_secret_value() if api_key is not None else None

    def missing_credential(self) -> str | None:
        """Every Last.fm API call needs a key."""
        return None if self._key else "needs lastfm.api_key"

    async def _call[M: models.ApiModel](self, model: type[M], method: str, **params: str) -> M:
        query = {"method": method, **params, "api_key": self._key or "", "format": "json"}
        response = await self.client.get(API, params=query)
        p.check(response.content, response.url)
        return model.model_validate_json(response.content)

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Read the track or album, its tags and wiki, the artist's tags, and similar items."""
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        if key.kind is EntityKind.ALBUM:
            return await self._album(key)
        return await self._track(key)

    async def _artist_tags(self, artist: str, page: str | None) -> list[Tag]:
        found = await self._call(
            models.TopTagsResponse,
            "artist.getTopTags",
            artist=artist,
            autocorrect="1",
        )
        return p.tags(found.toptags.tag, Scope.ARTIST, page, p.ARTIST_TAGS_LIMIT)

    async def _track(self, key: RecordKey) -> Partial:
        names = {"artist": key.artist, "track": key.title, "autocorrect": "1"}
        track = (await self._call(models.TrackInfoResponse, "track.getInfo", **names)).track

        names = {"artist": track.artist.name, "track": track.name}
        top = await self._call(models.TopTagsResponse, "track.getTopTags", **names)
        similar = await self._call(
            models.SimilarTracksResponse,
            "track.getSimilar",
            **names,
            limit=SIMILAR_TRACKS,
        )

        artist_page = track.artist.url or _artist_page(track.url)
        return Partial(
            source=self.name,
            candidate=p.track_candidate(track),
            tags=p.tags(top.toptags.tag, Scope.RECORDING, track.url)
            + await self._artist_tags(track.artist.name, artist_page),
            texts=p.wiki_texts(track.wiki, Scope.RECORDING, track.url),
            relations=p.similar_tracks(similar.similartracks.track, track.url),
        )

    async def _album(self, key: RecordKey) -> Partial:
        names = {"artist": key.artist, "album": key.title, "autocorrect": "1"}
        album = (await self._call(models.AlbumInfoResponse, "album.getInfo", **names)).album

        names = {"artist": album.artist, "album": album.name}
        top = await self._call(models.TopTagsResponse, "album.getTopTags", **names)
        similar = await self._call(
            models.SimilarArtistsResponse,
            "artist.getSimilar",
            artist=album.artist,
            limit=SIMILAR_ARTISTS,
        )

        artist_page = _artist_page(album.url)
        return Partial(
            source=self.name,
            candidate=p.album_candidate(album),
            tags=p.tags(top.toptags.tag, Scope.RELEASE_GROUP, album.url)
            + await self._artist_tags(album.artist, artist_page),
            texts=p.wiki_texts(album.wiki, Scope.RELEASE_GROUP, album.url),
            relations=p.similar_artists(similar.similar.artist, artist_page),
        )
