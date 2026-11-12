import pytest

from deadwax.core import (
    EntityKind,
    Identity,
    LinkTarget,
    LookupContext,
    Provenance,
    Sourced,
    VersionInfo,
    VersionKind,
    parse_query,
)
from deadwax.sources._base import link_target, search_key, service_for_url

SOURCES = [Provenance(source="musicbrainz")]


@pytest.mark.parametrize(
    ("url", "service"),
    [
        ("https://open.spotify.com/track/1", "spotify"),
        ("https://www.deezer.com/track/1", "deezer"),
        ("https://music.youtube.com/watch?v=1", "youtube_music"),
        ("https://www.youtube.com/watch?v=1", "youtube"),
        ("https://artist.bandcamp.com/album/x", "bandcamp"),
        ("https://www.discogs.com/master/1", None),
        ("not a url", None),
    ],
)
def test_service_for_url(url: str, service: str | None) -> None:
    assert service_for_url(url) == service


@pytest.mark.parametrize(
    ("url", "target"),
    [
        ("https://open.spotify.com/album/1", LinkTarget.ALBUM),
        ("https://open.spotify.com/track/1", LinkTarget.TRACK),
        ("https://www.youtube.com/channel/UC1", LinkTarget.ARTIST),
        ("https://tidal.com/browse/x", LinkTarget.OTHER),
    ],
)
def test_link_target(url: str, target: LinkTarget) -> None:
    assert link_target(url, LinkTarget.OTHER) is target


def test_search_key_prefers_the_query_text() -> None:
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)

    key = search_key(query, LookupContext(query=query))

    assert key is not None
    assert (key.artist, key.title, key.kind) == ("Radiohead", "Paranoid Android", EntityKind.TRACK)


def test_search_key_of_a_url_query_comes_from_earlier_passes() -> None:
    query = parse_query("https://example.org/record")
    remix = VersionInfo(kind=VersionKind.REMIX, detail="Todd Terry remix")
    identity = Identity(
        kind=EntityKind.TRACK,
        artist=Sourced(value="Everything but the Girl", sources=SOURCES),
        title=Sourced(value="Missing (Todd Terry remix)", sources=SOURCES),
        version=remix,
    )

    key = search_key(query, LookupContext(query=query, identity=identity))

    assert search_key(query, LookupContext(query=query)) is None
    assert key is not None
    assert (key.kind, key.version) == (EntityKind.TRACK, remix)
