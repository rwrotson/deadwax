import pytest

from deadwax.core import (
    LinkTarget,
)
from deadwax.sources.services import link_target, service_for_url


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
