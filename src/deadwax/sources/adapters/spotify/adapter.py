import base64
import dataclasses
from collections.abc import Mapping

from deadwax.core import (
    BlockedError,
    Capability,
    EntityKind,
    IdKind,
    LookupContext,
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
from deadwax.sources._http import HttpClient, HttpResources
from deadwax.sources._search import pick_hit, search_key
from deadwax.sources.adapters.spotify import models
from deadwax.sources.adapters.spotify import parse as p
from deadwax.sources.config import LookupConfig
from deadwax.sources.services import recognize

API = "https://api.spotify.com/v1/"
ACCOUNTS = "https://accounts.spotify.com/api/"

# Development-mode apps may ask for at most 10 search results.
SEARCH_LIMIT = "10"


def _quoted(text: str) -> str:
    return '"' + text.replace('"', " ") + '"'


class SpotifyAdapter(HttpAdapter):
    """Spotify links, codes, label, copyrights, and popularity from the Spotify Web API."""

    name = "spotify"
    pass_ = Pass.ENRICH
    group = SourceGroup.STREAMING
    service = "spotify"
    capabilities = frozenset(
        {Capability.IDENTITY, Capability.LINKS, Capability.PREVIEWS, Capability.METRICS},
    )
    requires = (
        Requirement(setting="sources.spotify.client_id", purpose="every lookup"),
        Requirement(setting="sources.spotify.client_secret", purpose="every lookup"),
    )

    def __init__(self, config: LookupConfig, resources: HttpResources) -> None:
        super().__init__(config, resources)
        self._token: str | None = None
        self._token_client: HttpClient | None = None

    def missing_credential(self) -> str | None:
        """Every Web API call needs an app's client ID and secret."""
        settings = self.config.sources.spotify
        if settings.client_id is None or settings.client_secret is None:
            return "needs sources.spotify.client_id and sources.spotify.client_secret"
        return None

    def resolves(self, query: Query) -> bool:
        """Spotify track and album URLs."""
        return IdKind.SPOTIFY in query.ids

    @property
    def token_client(self) -> HttpClient:
        """Client of the token endpoint; it shares the rate limits but not the response cache."""
        if self._token_client is None:
            resources = dataclasses.replace(self.resources, cache=None)
            self._token_client = HttpClient(
                self.client_spec(self.profile),
                self.client_settings,
                resources,
            )
        return self._token_client

    async def aclose(self) -> None:
        """Close both clients."""
        await super().aclose()
        if self._token_client is not None:
            await self._token_client.aclose()
            self._token_client = None

    async def _authorization(self) -> Mapping[str, str]:
        """Bearer header with a token fetched once per adapter and never stored on disk.

        A token lives an hour and the adapter one lookup, so it is not refreshed.
        """
        if self._token is None:
            settings = self.config.sources.spotify
            client_id = settings.client_id.get_secret_value() if settings.client_id else ""
            secret = settings.client_secret.get_secret_value() if settings.client_secret else ""
            basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
            try:
                response = await self.token_client.request(
                    "POST",
                    f"{ACCOUNTS}token",
                    headers={
                        "authorization": f"Basic {basic}",
                        "content-type": "application/x-www-form-urlencoded",
                    },
                    body=b"grant_type=client_credentials",
                )
            except BlockedError, NotFoundError, RateLimitedError:
                raise
            except SourceError as error:
                message = f"Spotify refused the client credentials ({error})"
                raise SourceError(message, url=error.url) from None
            self._token = models.Token.model_validate_json(response.content).access_token
        return {"authorization": f"Bearer {self._token}"}

    async def _get[M: models.ApiModel](self, model: type[M], url: str, **params: str) -> M:
        headers = await self._authorization()
        response = await self.client.get(url, params=params or None, headers=headers)
        return model.model_validate_json(response.content)

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Read the record by Spotify ID, else find it by ISRC or barcode, else by search."""
        key = search_key(query, context)
        kind = query.kind or (key.kind if key is not None else None) or EntityKind.TRACK

        spotify_id = query.ids.get(IdKind.SPOTIFY) or self._known_id(context, kind)
        if spotify_id is not None:
            return await self._read(kind, f"{API}{kind}s/{spotify_id}")

        url = await self._find_by_code(kind, key, context)
        if url is None:
            if key is None:
                raise NotFoundError("neither the query nor earlier sources name the record")
            url = await self._search(kind, key)
        return await self._read(kind, url)

    def _known_id(self, context: LookupContext, kind: EntityKind) -> str | None:
        """Spotify ID of the record from a link an earlier source found."""
        for url in context.urls(p.SERVICE):
            url_kind, ids = recognize(url)
            if url_kind is kind and IdKind.SPOTIFY in ids:
                return ids[IdKind.SPOTIFY]
        return None

    async def _read(self, kind: EntityKind, url: str) -> Partial:
        if kind is EntityKind.ALBUM:
            return p.album_partial(await self._get(models.Album, url))
        track = await self._get(models.Track, url)
        album = None
        if track.album is not None:
            album = await self._get(models.Album, f"{API}albums/{track.album.id}")
        return p.track_partial(track, album)

    async def _find_by_code(
        self,
        kind: EntityKind,
        key: RecordKey | None,
        context: LookupContext,
    ) -> str | None:
        """API URL of the record found by an ISRC or barcode from earlier passes."""
        codes = context.identity.isrcs if kind is EntityKind.TRACK else context.identity.upcs
        if not codes:
            return None
        field = "isrc" if kind is EntityKind.TRACK else "upc"
        results = await self._get(
            models.SearchResults,
            f"{API}search",
            q=f"{field}:{codes[0].value}",
            type=str(kind),
            limit=SEARCH_LIMIT,
        )
        hits = p.track_hits(results) if kind is EntityKind.TRACK else p.album_hits(results)
        if key is not None:
            hit = pick_hit(key, hits)
            return hit.url if hit is not None else None
        return hits[0].url if hits else None

    async def _search(self, kind: EntityKind, key: RecordKey) -> str:
        field = "track" if kind is EntityKind.TRACK else "album"
        results = await self._get(
            models.SearchResults,
            f"{API}search",
            q=f"{field}:{_quoted(key.title)} artist:{_quoted(key.artist)}",
            type=str(kind),
            limit=SEARCH_LIMIT,
        )
        hits = p.track_hits(results) if kind is EntityKind.TRACK else p.album_hits(results)
        hit = pick_hit(key, hits)
        if hit is None:
            raise NotFoundError(f"no matching Spotify {kind}")
        return hit.url
