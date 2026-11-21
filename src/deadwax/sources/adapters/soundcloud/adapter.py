from deadwax.core import (
    BlockedError,
    Capability,
    EntityKind,
    LookupContext,
    Lookups,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RateLimitedError,
    RecordKey,
    Requirement,
    SourceError,
    SourceGroup,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._http import Response
from deadwax.sources._search import pick_hit, search_key
from deadwax.sources.adapters.soundcloud import models
from deadwax.sources.adapters.soundcloud import parse as p

API = "https://api-v2.soundcloud.com/"
SEARCH_RESULTS = "20"
REPOSTERS = "50"


class SoundCloudAdapter(HttpAdapter):
    """Uploader descriptions, tags, counts, and reposters of the record's SoundCloud upload."""

    name = "soundcloud"
    pass_ = Pass.ENRICH
    group = SourceGroup.STREAMING
    service = p.SERVICE
    capabilities = frozenset(
        {
            Capability.IDENTITY,
            Capability.LINKS,
            Capability.TAGS,
            Capability.TEXTS,
            Capability.RELATIONS,
            Capability.METRICS,
        },
    )
    requires = (Requirement(setting="sources.soundcloud.client_id", purpose="every lookup"),)
    secret_params = frozenset({"client_id"})

    @property
    def _client_id(self) -> str | None:
        client_id = self.config.sources.soundcloud.client_id
        return client_id.get_secret_value() if client_id is not None else None

    def missing_credential(self) -> str | None:
        """Every API call needs a client ID."""
        return None if self._client_id else "needs sources.soundcloud.client_id"

    async def _get(self, path: str, **params: str) -> Response:
        try:
            return await self.client.get(
                f"{API}{path}",
                params={**params, "client_id": self._client_id or ""},
            )
        except BlockedError, NotFoundError, RateLimitedError:
            raise
        except SourceError as error:
            message = (
                f"SoundCloud refused the request ({error}); is sources.soundcloud.client_id stale?"
            )
            raise SourceError(message, url=error.url) from None

    @property
    def lookups(self) -> Lookups:
        """Tracks and release sets; the resolved upload tells which."""
        return Lookups(track=self.find, album=self.find, unresolved=self.find)

    async def find(self, query: Query, context: LookupContext) -> Partial:
        """Read the upload behind the query URL, an earlier source's link, or a search."""
        key = search_key(query, context)
        kind = query.kind or (key.kind if key is not None else None) or EntityKind.TRACK

        if query.url is not None and self.resolves(query):
            page = query.url
        elif known := context.urls(p.SERVICE):
            page = known[0]
        elif key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        else:
            page = await self._search(key, kind)

        resolved = await self._get("resolve", url=page)
        item, kind = self._item(resolved)
        collection = "tracks" if kind is EntityKind.TRACK else "playlists"
        try:
            users = await self._get(f"{collection}/{item.id}/reposters", limit=REPOSTERS)
            reposted_by = models.Users.model_validate_json(users.content)
        except NotFoundError:
            reposted_by = models.Users()
        return p.partial(item, kind, reposted_by)

    def _item(self, response: Response) -> tuple[models.Item, EntityKind]:
        """Read a resolved track or release set; a listener's playlist is not a record."""
        kind = models.Resolved.model_validate_json(response.content).kind
        if kind == "track":
            return models.Track.model_validate_json(response.content), EntityKind.TRACK
        if kind == "playlist":
            playlist = models.Playlist.model_validate_json(response.content)
            if (playlist.set_type or "") in p.ALBUM_SET_TYPES:
                return playlist, EntityKind.ALBUM
            raise NotFoundError("the SoundCloud set is a playlist, not a release", url=response.url)
        raise NotFoundError(f"the SoundCloud page is a {kind}, not a record", url=response.url)

    async def _search(self, key: RecordKey, kind: EntityKind) -> str:
        query = f"{key.artist} {key.title}"
        if kind is EntityKind.ALBUM:
            albums = await self._get("search/albums", q=query, limit=SEARCH_RESULTS)
            hits = p.album_hits(
                models.PlaylistSearch.model_validate_json(albums.content),
                key.artist,
            )
        else:
            tracks = await self._get("search/tracks", q=query, limit=SEARCH_RESULTS)
            hits = p.track_hits(
                models.TrackSearch.model_validate_json(tracks.content),
                key.artist,
            )
        hit = pick_hit(key, hits)
        if hit is None:
            raise NotFoundError(f"no matching SoundCloud {kind}")
        return hit.url
