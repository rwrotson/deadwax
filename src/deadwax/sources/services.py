import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from deadwax.core import (
    EntityKind,
    IdKind,
    InvalidQueryError,
    LinkTarget,
    Query,
    UrlRule,
    isrc_ids,
    recognize_url,
    text_query,
)


@dataclass(frozen=True, slots=True)
class Service:
    """A web service: its hosts and the URL rules of its record pages."""

    name: str

    # Matched against the end of the URL host, so subdomains belong to the service.
    hosts: tuple[str, ...]

    rules: tuple[UrlRule, ...] = ()

    # Whether its URLs count as streaming or store links.
    link: bool = True

    def owns(self, url: str) -> bool:
        """Whether the URL's host belongs to the service."""
        host = (urlsplit(url).hostname or "").lower()
        return any(host == suffix or host.endswith(f".{suffix}") for suffix in self.hosts)


_MBID = r"(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"

# A SoundCloud track page is '/<user>/<track>', optionally with a secret-link token; the
# names below are site sections and profile tabs, not users and tracks. Sets ('/<user>/sets/')
# are albums or playlists, which only the resolver can tell apart.
_SOUNDCLOUD_TRACK = re.compile(
    r"^/(?!(?:discover|search|charts|stream|you|upload|pages|settings|messages|notifications|"
    r"people|tags|terms-of-use)/)[^/]+/(?!(?:sets|likes|tracks|albums|reposts|followers|"
    r"following|popular-tracks|comments|spotlight)(?:/|$))[^/]+(?:/s-\w+)?/?$",
)

# Services in the order their hosts are tried: a more specific host comes first.
SERVICES = (
    Service(
        "spotify",
        ("open.spotify.com",),
        (
            UrlRule(
                re.compile(r"^(?:/intl-[a-z]+)?/track/(?P<id>\w+)"),
                EntityKind.TRACK,
                IdKind.SPOTIFY,
            ),
            UrlRule(
                re.compile(r"^(?:/intl-[a-z]+)?/album/(?P<id>\w+)"),
                EntityKind.ALBUM,
                IdKind.SPOTIFY,
            ),
        ),
    ),
    Service(
        "apple_music",
        ("music.apple.com", "itunes.apple.com"),
        (
            UrlRule(
                re.compile(r"^/[a-z]{2}/song/(?:[^/]+/)?(?P<id>\d+)"),
                EntityKind.TRACK,
                IdKind.APPLE_MUSIC,
            ),
            # An album URL points at one of its tracks when it carries the `i` parameter.
            UrlRule(
                re.compile(r"^/[a-z]{2}/album/(?:[^/]+/)?\d+"),
                EntityKind.TRACK,
                IdKind.APPLE_MUSIC,
                param="i",
            ),
            UrlRule(
                re.compile(r"^/[a-z]{2}/album/(?:[^/]+/)?(?P<id>\d+)"),
                EntityKind.ALBUM,
                IdKind.APPLE_MUSIC,
            ),
        ),
    ),
    Service(
        "deezer",
        ("deezer.com",),
        (
            UrlRule(
                re.compile(r"^(?:/[a-z]{2})?/track/(?P<id>\d+)"),
                EntityKind.TRACK,
                IdKind.DEEZER,
            ),
            UrlRule(
                re.compile(r"^(?:/[a-z]{2})?/album/(?P<id>\d+)"),
                EntityKind.ALBUM,
                IdKind.DEEZER,
            ),
        ),
    ),
    Service("tidal", ("tidal.com",)),
    Service("youtube_music", ("music.youtube.com",)),
    Service("youtube", ("youtube.com", "youtu.be")),
    Service(
        "bandcamp",
        ("bandcamp.com",),
        (
            UrlRule(re.compile(r"^/album/"), EntityKind.ALBUM),
            UrlRule(re.compile(r"^/track/"), EntityKind.TRACK),
        ),
    ),
    Service("soundcloud", ("soundcloud.com",), (UrlRule(_SOUNDCLOUD_TRACK, EntityKind.TRACK),)),
    Service("amazon_music", ("music.amazon.com",)),
    Service("amazon", ("amazon.com",)),
    Service(
        "beatport",
        ("beatport.com",),
        (
            UrlRule(
                re.compile(r"^(?:/[a-z]{2})?/track/[^/]+/(?P<id>\d+)"),
                EntityKind.TRACK,
                IdKind.BEATPORT_TRACK,
            ),
            UrlRule(
                re.compile(r"^(?:/[a-z]{2})?/release/[^/]+/(?P<id>\d+)"),
                EntityKind.ALBUM,
                IdKind.BEATPORT_RELEASE,
            ),
        ),
    ),
    Service("qobuz", ("qobuz.com",)),
    Service("napster", ("napster.com",)),
    Service("pandora", ("pandora.com",)),
    Service("audiomack", ("audiomack.com",)),
    Service(
        "boomkat",
        ("boomkat.com",),
        (
            UrlRule(re.compile(r"^/artists/[^/]+/releases/[^/]+/[^/]+"), EntityKind.ALBUM),
            UrlRule(re.compile(r"^/products/[^/]+"), EntityKind.ALBUM),
        ),
    ),
    Service(
        "norman",
        ("normanrecords.com",),
        (UrlRule(re.compile(r"^/records/\d+-"), EntityKind.ALBUM),),
    ),
    Service("junodownload", ("junodownload.com",)),
    Service(
        "juno",
        ("juno.co.uk",),
        (UrlRule(re.compile(r"^/products/[^/]+/\d+-\d+"), EntityKind.ALBUM),),
    ),
    Service("hardwax", ("hardwax.com",), (UrlRule(re.compile(r"^/\d+/"), EntityKind.ALBUM),)),
    Service(
        "phonica",
        ("phonicarecords.com",),
        (UrlRule(re.compile(r"^/product/[^/]+/\d+"), EntityKind.ALBUM),),
    ),
    Service(
        "soundohm",
        ("soundohm.com",),
        (UrlRule(re.compile(r"^/product/[^/]+"), EntityKind.ALBUM),),
    ),
    Service("bleep", ("bleep.com",), (UrlRule(re.compile(r"^/release/\d+"), EntityKind.ALBUM),)),
    Service(
        "forcedexposure",
        ("forcedexposure.com",),
        (UrlRule(re.compile(r"^/Catalog/.+\.html$"), EntityKind.ALBUM),),
    ),
    Service(
        "allmusic",
        ("allmusic.com",),
        (
            UrlRule(re.compile(r"^/album/"), EntityKind.ALBUM),
            UrlRule(re.compile(r"^/song/"), EntityKind.TRACK),
        ),
    ),
    Service(
        "albumoftheyear",
        ("albumoftheyear.org",),
        (UrlRule(re.compile(r"^/album/"), EntityKind.ALBUM),),
    ),
    Service(
        "rateyourmusic",
        ("rateyourmusic.com",),
        (
            UrlRule(re.compile(r"^/release/"), EntityKind.ALBUM),
            UrlRule(re.compile(r"^/song/"), EntityKind.TRACK),
        ),
    ),
    Service(
        "whosampled",
        ("whosampled.com",),
        (UrlRule(re.compile(r"^/[^/]+/[^/]+/?$"), EntityKind.TRACK),),
    ),
    Service(
        "tracklists",
        ("1001tracklists.com",),
        (UrlRule(re.compile(r"^/track/[^/]+/[^/]+/"), EntityKind.TRACK),),
    ),
    Service("7digital", ("7digital.com",)),
    Service(
        "musicbrainz",
        ("musicbrainz.org",),
        (
            UrlRule(
                re.compile(rf"^/recording/{_MBID}"),
                EntityKind.TRACK,
                IdKind.MUSICBRAINZ_RECORDING,
            ),
            UrlRule(
                re.compile(rf"^/release-group/{_MBID}"),
                EntityKind.ALBUM,
                IdKind.MUSICBRAINZ_RELEASE_GROUP,
            ),
            UrlRule(
                re.compile(rf"^/release/{_MBID}"),
                EntityKind.ALBUM,
                IdKind.MUSICBRAINZ_RELEASE,
            ),
        ),
        link=False,
    ),
    Service(
        "discogs",
        ("discogs.com",),
        (
            UrlRule(
                re.compile(r"^(?:/[^/]+)?/release/(?P<id>\d+)"),
                EntityKind.ALBUM,
                IdKind.DISCOGS_RELEASE,
            ),
            UrlRule(
                re.compile(r"^(?:/[^/]+)?/master/(?P<id>\d+)"),
                EntityKind.ALBUM,
                IdKind.DISCOGS_MASTER,
            ),
        ),
        link=False,
    ),
)


def service_of(url: str) -> Service | None:
    """Find the service a URL belongs to."""
    return next((service for service in SERVICES if service.owns(url)), None)


def service_for_url(url: str) -> str | None:
    """Name the streaming or store service a URL belongs to, if it is a known one."""
    service = service_of(url)
    return service.name if service is not None and service.link else None


def recognize(url: str) -> tuple[EntityKind | None, dict[IdKind, str]]:
    """Infer the record kind and identifiers from a known service URL."""
    service = service_of(url)
    return recognize_url(url, service.rules) if service is not None else (None, {})


def link_target(url: str, default: LinkTarget) -> LinkTarget:
    """Tell whether a service URL opens a track or an album, falling back to a default."""
    kind, _ = recognize(url)
    if kind is EntityKind.TRACK:
        return LinkTarget.TRACK
    if kind is EntityKind.ALBUM:
        return LinkTarget.ALBUM
    if re.search(r"/(?:artist|channel|user)/", urlsplit(url).path):
        return LinkTarget.ARTIST
    return default


def _url_query(url: str, kind: EntityKind | None, isrc: str | None) -> Query:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise InvalidQueryError(f"not an HTTP(S) URL: {url}")
    url_kind, ids = recognize(url)
    if kind is not None and url_kind is not None and kind != url_kind:
        raise InvalidQueryError(f"the URL points to a {url_kind}, but a {kind} was requested")
    kind = kind or url_kind
    return Query(kind=kind, url=url, ids=ids | isrc_ids(isrc, kind))


def parse_query(
    text: str,
    kind: EntityKind | None = None,
    *,
    isrc: str | None = None,
) -> Query:
    """Build a query from 'Artist - Title' text or a record page URL, and an optional ISRC."""
    text = text.strip()
    if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.IGNORECASE):
        return _url_query(text, kind, isrc)
    return text_query(text, kind, isrc=isrc)
