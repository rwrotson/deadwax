import re
from urllib.parse import urlsplit

from deadwax.core import (
    EntityKind,
    LinkTarget,
    recognize_url,
)

# Hosts of streaming and store services, matched against the end of the URL host.
_SERVICES = (
    ("open.spotify.com", "spotify"),
    ("music.apple.com", "apple_music"),
    ("itunes.apple.com", "apple_music"),
    ("deezer.com", "deezer"),
    ("tidal.com", "tidal"),
    ("music.youtube.com", "youtube_music"),
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("bandcamp.com", "bandcamp"),
    ("soundcloud.com", "soundcloud"),
    ("music.amazon.com", "amazon_music"),
    ("amazon.com", "amazon"),
    ("beatport.com", "beatport"),
    ("qobuz.com", "qobuz"),
    ("napster.com", "napster"),
    ("pandora.com", "pandora"),
    ("audiomack.com", "audiomack"),
    ("boomkat.com", "boomkat"),
    ("normanrecords.com", "norman"),
    ("junodownload.com", "junodownload"),
    ("juno.co.uk", "juno"),
    ("hardwax.com", "hardwax"),
    ("phonicarecords.com", "phonica"),
    ("soundohm.com", "soundohm"),
    ("bleep.com", "bleep"),
    ("forcedexposure.com", "forcedexposure"),
    ("allmusic.com", "allmusic"),
    ("albumoftheyear.org", "albumoftheyear"),
    ("rateyourmusic.com", "rateyourmusic"),
    ("whosampled.com", "whosampled"),
    ("1001tracklists.com", "tracklists"),
    ("7digital.com", "7digital"),
)


def service_for_url(url: str) -> str | None:
    """Name the streaming or store service a URL belongs to, if it is a known one."""
    host = (urlsplit(url).hostname or "").lower()
    for suffix, service in _SERVICES:
        if host == suffix or host.endswith(f".{suffix}"):
            return service
    return None


def link_target(url: str, default: LinkTarget) -> LinkTarget:
    """Tell whether a service URL opens a track or an album, falling back to a default."""
    kind, _ = recognize_url(url)
    if kind is EntityKind.TRACK:
        return LinkTarget.TRACK
    if kind is EntityKind.ALBUM:
        return LinkTarget.ALBUM
    if re.search(r"/(?:artist|channel|user)/", urlsplit(url).path):
        return LinkTarget.ARTIST
    return default
