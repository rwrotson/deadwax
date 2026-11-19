import re

from pydantic import ValidationError

from deadwax.core import (
    EntityKind,
    Link,
    LinkTarget,
    LookupContext,
    NotFoundError,
    Partial,
    Provenance,
    Query,
    RecordCandidate,
    SourceError,
)
from deadwax.sources._html import parse_html
from deadwax.sources.adapters.odesli.models import Entity, NextData, PageData, PlatformLink
from deadwax.sources.services import service_for_url

SOURCE = "odesli"
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

# Platforms whose links name records in the ID space of an entity provider.
_PROVIDER_PLATFORMS = {
    "itunes": frozenset({"appleMusic", "itunes"}),
    "youtube": frozenset({"youtube", "youtubeMusic"}),
    "amazon": frozenset({"amazonMusic", "amazonStore"}),
}


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
        data = NextData.model_validate_json(script.text())
    except ValidationError as error:
        raise SourceError(f"unexpected song.link page data: {error.error_count()} errors") from None
    if data.props.page_props.page_data is None:
        raise NotFoundError("song.link does not know this record", url=url)
    return data.props.page_props.page_data


def contradicts(entity: Entity | None, link: PlatformLink) -> bool:
    """Whether a link on the entity's own provider names another record than the entity.

    song.link sometimes links a different version on the seed's platform, such as an
    instrumental of the seed track.
    """
    if entity is None or entity.provider is None or entity.id is None or link.url is None:
        return False
    platforms = _PROVIDER_PLATFORMS.get(entity.provider, frozenset({entity.provider}))
    if link.platform not in platforms:
        return False
    return entity.id not in re.findall(r"[A-Za-z0-9]+", link.url)


def partial(data: PageData) -> Partial:
    """Describe the record and list its link on every platform Odesli matched."""
    entity = data.entity
    kind = EntityKind.ALBUM if entity is not None and entity.type == "album" else EntityKind.TRACK
    target = LinkTarget.ALBUM if kind is EntityKind.ALBUM else LinkTarget.TRACK
    sources = [Provenance(source=SOURCE, url=data.page_url)]

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
        if link.url
        and link.show
        and re.match(r"^https?://", link.url)
        and not contradicts(entity, link)
    }

    return Partial(
        source=SOURCE,
        candidate=candidate,
        links=[
            Link(service=service_name(link.platform), url=url, target=target, sources=sources)
            for url, link in found.items()
        ],
    )


def seed(query: Query, context: LookupContext) -> str | None:
    """Pick the streaming URL that Odesli starts from."""
    if query.url is not None and service_for_url(query.url) in _SEED_SERVICES:
        return query.url
    for service in _SEED_SERVICES:
        urls = context.urls(service)
        if urls:
            return urls[0]
    return None
