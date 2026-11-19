from deadwax.core import (
    BlockedError,
    Capability,
    EntityKind,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Query,
    RateLimitedError,
    Requirement,
    SourceError,
    SourceGroup,
)
from deadwax.sources._adapter import HttpAdapter
from deadwax.sources._search import search_key
from deadwax.sources.adapters.youtube import parse
from deadwax.sources.adapters.youtube.models import SearchResponse


class YouTubeAdapter(HttpAdapter):
    """Links to the record's uploads on YouTube, official ones first; no other facts."""

    name = parse.SOURCE
    pass_ = Pass.LINKS
    group = SourceGroup.STREAMING
    capabilities = frozenset({Capability.LINKS})
    requires = (Requirement(setting="youtube.api_key", purpose="every lookup"),)
    secret_params = frozenset({"key"})

    @property
    def _key(self) -> str | None:
        api_key = self.config.youtube.api_key
        return api_key.get_secret_value() if api_key is not None else None

    def missing_credential(self) -> str | None:
        """Every Data API call needs a key."""
        return None if self._key else "needs youtube.api_key"

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Search music videos, or playlists for an album, and keep uploads of the record."""
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("neither the query nor earlier sources name the record")
        kind = key.kind or EntityKind.TRACK

        params = {
            "part": "snippet",
            "q": f"{key.artist} {key.title}",
            "maxResults": parse.SEARCH_RESULTS,
            "key": self._key or "",
        }
        if kind is EntityKind.ALBUM:
            params["type"] = "playlist"
        else:
            params |= {"type": "video", "videoCategoryId": parse.MUSIC_CATEGORY}
        try:
            response = await self.client.get(f"{parse.API}search", params=params)
        except BlockedError, NotFoundError, RateLimitedError:
            raise
        except SourceError as error:
            message = f"YouTube refused the search ({error}): a spent daily quota or a bad key"
            raise SourceError(message, url=error.url) from None

        items = SearchResponse.model_validate_json(response.content).items
        links = parse.matching_links(items, key, kind)
        if not links:
            raise NotFoundError("no YouTube upload of the record", url=response.url)
        return Partial(source=self.name, links=links)
