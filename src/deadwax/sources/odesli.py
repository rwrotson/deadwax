import re
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    SourceError,
)
from deadwax.sources._base import HttpAdapter, service_for_url
from deadwax.sources._html import parse_html
from deadwax.sources._http import Profile

SITE = "https://song.link/"

# Services whose URLs Odesli accepts as a starting point, best matches first: a Spotify seed
# finds the most platforms.
_SEED_SERVICES = ("spotify", "apple_music", "deezer", "tidal", "youtube_music", "youtube")

# Platform names that differ from the service names used elsewhere in deadwax.
_PLATFORMS = {
    "appleMusic": "apple_music",
    "itunes": "itunes_store",
    "youtubeMusic": "youtube_music",
}


class _Page(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class Entity(_Page):
    """Song or album the page is about, as the seed platform knows it."""

    type: str
    title: str | None = None
    artist_name: str | None = Field(default=None, alias="artistName")
    isrc: str | None = None
    upc: str | None = None


class PlatformLink(_Page):
    """Link of one platform; platforms Odesli did not match have no URL."""

    platform: str
    url: str | None = None
    show: bool = True


class Section(_Page):
    """Block of the page, such as the 'listen' and 'buy' link lists."""

    section_id: str = Field(default="", alias="sectionId")
    links: list[PlatformLink] = []


class PageData(_Page):
    """Data the song.link page renders."""

    entity_unique_id: str = Field(alias="entityUniqueId")
    page_url: str | None = Field(default=None, alias="pageUrl")
    entity: Entity | None = Field(default=None, alias="entityData")
    sections: list[Section] = []


def service_name(platform: str) -> str:
    """Convert an Odesli platform name such as 'amazonMusic' to 'amazon_music'."""
    return _PLATFORMS.get(platform) or re.sub(r"(?<!^)([A-Z])", r"_\1", platform).lower()


def page_data(content: bytes, url: str) -> PageData:
    """Read the page data from the Next.js script of a song.link page.

    An unknown URL redirects to a page without data, which means not found.
    """
    script = parse_html(content).css_first("script#__NEXT_DATA__")
    if script is None:
        raise SourceError("the song.link page has no page data", url=url)
    try:
        data = _NextData.model_validate_json(script.text())
    except ValidationError as error:
        raise SourceError(f"unexpected song.link page data: {error.error_count()} errors") from None
    if data.props.page_props.page_data is None:
        raise NotFoundError("song.link does not know this record", url=url)
    return data.props.page_props.page_data


class _PageProps(_Page):
    page_data: PageData | None = Field(default=None, alias="pageData")


class _Props(_Page):
    page_props: _PageProps = Field(default=_PageProps(), alias="pageProps")


class _NextData(_Page):
    props: _Props = _Props()


def partial(data: PageData) -> Partial:
    """Describe the record and list its link on every platform Odesli matched."""
    entity = data.entity
    kind = EntityKind.ALBUM if entity is not None and entity.type == "album" else EntityKind.TRACK
    target = LinkTarget.ALBUM if kind is EntityKind.ALBUM else LinkTarget.TRACK
    sources = [Provenance(source=OdesliAdapter.name, url=data.page_url)]
    candidate = None
    if entity is not None and entity.title and entity.artist_name:
        candidate = RecordCandidate(
            kind=kind,
            artist=entity.artist_name,
            title=entity.title,
            isrcs=[entity.isrc] if entity.isrc else [],
            upcs=[entity.upc] if entity.upc else [],
            url=data.page_url,
        )
    found = {
        link.url: link
        for section in data.sections
        for link in section.links
        if link.url and link.show and re.match(r"^https?://", link.url)
    }
    return Partial(
        source=OdesliAdapter.name,
        candidate=candidate,
        links=[
            Link(service=service_name(link.platform), url=url, target=target, sources=sources)
            for url, link in found.items()
        ],
    )


class OdesliAdapter(HttpAdapter):
    """Links on every streaming platform from the song.link page of a streaming link."""

    name = "odesli"
    pass_ = Pass.ENRICH
    capabilities = frozenset({Capability.LINKS})
    profile = Profile.BROWSER

    def resolves(self, query: Query) -> bool:
        """Streaming service URLs."""
        return any(
            kind in query.ids for kind in (IdKind.SPOTIFY, IdKind.APPLE_MUSIC, IdKind.DEEZER)
        )

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Open the song.link page of a streaming URL from the query or an earlier pass."""
        seed = _seed(query, context)
        if seed is None:
            raise NotFoundError("no streaming URL to start from")
        # Encoded, the seed keeps its own query (Apple's track `?i=`) and song.link answers
        # with one redirect to the record's page instead of normalizing the path first.
        response = await self.client.get(f"{SITE}{quote(seed, safe='')}")
        return partial(page_data(response.content, response.url))


def _seed(query: Query, context: LookupContext) -> str | None:
    if query.url is not None and service_for_url(query.url) in _SEED_SERVICES:
        return query.url
    for service in _SEED_SERVICES:
        urls = context.urls(service)
        if urls:
            return urls[0]
    return None
