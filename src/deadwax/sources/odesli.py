import re

from pydantic import BaseModel, ConfigDict, Field

from deadwax.core import (
    Capability,
    EntityKind,
    IdKind,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RecordCandidate,
    Requirement,
)
from deadwax.sources._base import HttpAdapter, service_for_url

API = "https://api.song.link/v1-alpha.1/links"

# Services whose URLs Odesli accepts as a starting point, in order of preference.
_SEED_SERVICES = ("spotify", "apple_music", "deezer", "tidal", "youtube_music", "youtube")

# Platform names that differ from the service names used elsewhere in deadwax.
_PLATFORMS = {
    "appleMusic": "apple_music",
    "itunes": "itunes_store",
    "youtubeMusic": "youtube_music",
}


class _Api(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Entity(_Api):
    """Song or album as one platform knows it."""

    type: str
    title: str | None = None
    artist_name: str | None = Field(default=None, alias="artistName")


class PlatformLink(_Api):
    """Link of one platform."""

    url: str
    entity_unique_id: str | None = Field(default=None, alias="entityUniqueId")


class Links(_Api):
    """Response of the links endpoint."""

    entity_unique_id: str = Field(alias="entityUniqueId")
    page_url: str | None = Field(default=None, alias="pageUrl")
    entities_by_unique_id: dict[str, Entity] = Field(default={}, alias="entitiesByUniqueId")
    links_by_platform: dict[str, PlatformLink] = Field(default={}, alias="linksByPlatform")


def service_name(platform: str) -> str:
    """Convert an Odesli platform name such as 'amazonMusic' to 'amazon_music'."""
    return _PLATFORMS.get(platform) or re.sub(r"(?<!^)([A-Z])", r"_\1", platform).lower()


def partial(links: Links) -> Partial:
    """Describe the record and list its link on every platform Odesli knows."""
    entity = links.entities_by_unique_id.get(links.entity_unique_id)
    kind = EntityKind.ALBUM if entity is not None and entity.type == "album" else EntityKind.TRACK
    target = LinkTarget.ALBUM if kind is EntityKind.ALBUM else LinkTarget.TRACK
    sources = [Provenance(source=OdesliAdapter.name, url=links.page_url)]
    candidate = None
    if entity is not None and entity.title and entity.artist_name:
        candidate = RecordCandidate(
            kind=kind, artist=entity.artist_name, title=entity.title, url=links.page_url
        )
    return Partial(
        source=OdesliAdapter.name,
        candidate=candidate,
        links=[
            Link(service=service_name(platform), url=link.url, target=target, sources=sources)
            for platform, link in sorted(links.links_by_platform.items())
        ],
    )


class OdesliAdapter(HttpAdapter):
    """Links on every streaming platform from Odesli (song.link); needs an API key."""

    name = "odesli"
    pass_ = Pass.ENRICH
    capabilities = frozenset({Capability.LINKS})
    requires = (Requirement(setting="odesli.api_key", purpose="every lookup"),)
    secret_params = frozenset({"key"})

    @property
    def _key(self) -> str | None:
        api_key = self.config.odesli.api_key
        return api_key.get_secret_value() if api_key is not None else None

    def missing_credential(self) -> str | None:
        """The keyless API was retired, so every lookup needs a key."""
        return None if self._key else "needs odesli.api_key; the keyless API was retired"

    def resolves(self, query: Query) -> bool:
        """Streaming service URLs."""
        return any(
            kind in query.ids for kind in (IdKind.SPOTIFY, IdKind.APPLE_MUSIC, IdKind.DEEZER)
        )

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Expand a streaming URL from the query or an earlier pass into links on all platforms."""
        seed = _seed(query, context)
        if seed is None:
            raise NotFoundError("no streaming URL to start from")
        response = await self.client.get(
            API, params={"url": seed, "userCountry": "US", "key": self._key or ""}
        )
        return partial(Links.model_validate_json(response.content))


def _seed(query: Query, context: LookupContext) -> str | None:
    if query.url is not None and service_for_url(query.url) in _SEED_SERVICES:
        return query.url
    for service in _SEED_SERVICES:
        urls = context.urls(service)
        if urls:
            return urls[0]
    return None
