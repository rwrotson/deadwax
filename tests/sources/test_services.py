import pytest

from deadwax.core import EntityKind, IdKind, InvalidQueryError, LinkTarget
from deadwax.sources import parse_query
from deadwax.sources.services import SERVICES, link_target, recognize, service_for_url, service_of

MBID = "0bb4fdaa-e4f6-4a6b-8d0a-9c5a7e44fd6a"


@pytest.mark.parametrize(
    ("url", "service"),
    [
        ("https://open.spotify.com/track/1", "spotify"),
        ("https://www.deezer.com/track/1", "deezer"),
        ("https://music.youtube.com/watch?v=1", "youtube_music"),
        ("https://www.youtube.com/watch?v=1", "youtube"),
        ("https://artist.bandcamp.com/album/x", "bandcamp"),
        ("https://www.discogs.com/master/1", None),
        (f"https://musicbrainz.org/recording/{MBID}", None),
        ("https://www.juno.co.uk/products/x/1-01/", "juno"),
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


def test_service_names_are_unique() -> None:
    names = [service.name for service in SERVICES]

    assert len(names) == len(set(names))


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("https://www.discogs.com/master/1", "discogs"),
        ("https://user:pw@m.soundcloud.com:443/a/b", "soundcloud"),
        ("https://music.youtube.com/watch?v=1", "youtube_music"),
        ("https://notbandcamp.com/album/x", None),
    ],
)
def test_service_of_matches_host_suffix(url: str, name: str | None) -> None:
    service = service_of(url)

    assert (service.name if service is not None else None) == name


@pytest.mark.parametrize(
    ("url", "kind", "ids"),
    [
        ("https://burial.bandcamp.com/album/untrue", EntityKind.ALBUM, {}),
        ("https://burial.bandcamp.com/track/archangel", EntityKind.TRACK, {}),
        (
            f"https://musicbrainz.org/recording/{MBID}",
            EntityKind.TRACK,
            {IdKind.MUSICBRAINZ_RECORDING: MBID},
        ),
        (
            f"https://musicbrainz.org/release-group/{MBID}",
            EntityKind.ALBUM,
            {IdKind.MUSICBRAINZ_RELEASE_GROUP: MBID},
        ),
        (
            f"https://musicbrainz.org/release/{MBID}",
            EntityKind.ALBUM,
            {IdKind.MUSICBRAINZ_RELEASE: MBID},
        ),
        (
            "https://www.discogs.com/release/1067734-Burial-Untrue",
            EntityKind.ALBUM,
            {IdKind.DISCOGS_RELEASE: "1067734"},
        ),
        (
            "https://www.discogs.com/Burial-Untrue/master/89497",
            EntityKind.ALBUM,
            {IdKind.DISCOGS_MASTER: "89497"},
        ),
        (
            "https://open.spotify.com/intl-de/track/3a1lNhkSLSkpJE4MSHpDu9",
            EntityKind.TRACK,
            {IdKind.SPOTIFY: "3a1lNhkSLSkpJE4MSHpDu9"},
        ),
        (
            "https://open.spotify.com/album/1z5ytkAaVoqdjKp1y4cv3q",
            EntityKind.ALBUM,
            {IdKind.SPOTIFY: "1z5ytkAaVoqdjKp1y4cv3q"},
        ),
        ("https://www.deezer.com/en/track/3135556", EntityKind.TRACK, {IdKind.DEEZER: "3135556"}),
        ("https://deezer.com/album/302127", EntityKind.ALBUM, {IdKind.DEEZER: "302127"}),
        (
            "https://music.apple.com/gb/album/untrue/266476563?i=266476578",
            EntityKind.TRACK,
            {IdKind.APPLE_MUSIC: "266476578"},
        ),
        (
            "https://music.apple.com/gb/album/untrue/266476563",
            EntityKind.ALBUM,
            {IdKind.APPLE_MUSIC: "266476563"},
        ),
        (
            "https://music.apple.com/us/song/archangel/266476578",
            EntityKind.TRACK,
            {IdKind.APPLE_MUSIC: "266476578"},
        ),
        (
            "https://music.apple.com/gb/song/1097861770",
            EntityKind.TRACK,
            {IdKind.APPLE_MUSIC: "1097861770"},
        ),
        (
            "https://music.apple.com/us/album/1097861387",
            EntityKind.ALBUM,
            {IdKind.APPLE_MUSIC: "1097861387"},
        ),
        ("https://soundcloud.com/burial/archangel", EntityKind.TRACK, {}),
        ("https://m.soundcloud.com/burial/archangel/s-AbC12/", EntityKind.TRACK, {}),
        ("https://soundcloud.com/burial/sets/untrue", None, {}),
        ("https://soundcloud.com/burial/likes", None, {}),
        ("https://soundcloud.com/discover/sets/new", None, {}),
        ("https://soundcloud.com/burial", None, {}),
        ("https://song.link/s/3a1lNhkSLSkpJE4MSHpDu9", None, {}),
        ("https://burial.bandcamp.com/", None, {}),
        ("https://hardwax.com/55357/burial/untrue/?focus=download", EntityKind.ALBUM, {}),
        ("https://hardwax.com/act/burial/", None, {}),
        ("https://www.soundohm.com/product/untrue", EntityKind.ALBUM, {}),
        ("https://www.soundohm.com/artist/burial", None, {}),
        ("https://www.juno.co.uk/products/burial-untrue-vinyl/285827-01/", EntityKind.ALBUM, {}),
        ("https://www.juno.co.uk/artists/Burial/", None, {}),
        (
            "https://www.phonicarecords.com/product/burial-truant-rough-sleeper-hyperdub/111124",
            EntityKind.ALBUM,
            {},
        ),
        ("https://www.whosampled.com/Daft-Punk/One-More-Time/", EntityKind.TRACK, {}),
        (
            "https://itunes.apple.com/us/album/untrue/266476563",
            EntityKind.ALBUM,
            {IdKind.APPLE_MUSIC: "266476563"},
        ),
        ("https://example.com/album/x", None, {}),
        (
            "https://www.1001tracklists.com/track/j4rvgx/daft-punk-one-more-time/index.html",
            EntityKind.TRACK,
            {},
        ),
    ],
)
def test_url_kind_and_ids_are_recognized(
    url: str,
    kind: EntityKind | None,
    ids: dict[IdKind, str],
) -> None:
    assert recognize(url) == (kind, ids)

    query = parse_query(url)

    assert (query.kind, query.url, query.ids) == (kind, url, ids)


def test_flag_sets_kind_of_unrecognized_url() -> None:
    query = parse_query("https://example.com/release", EntityKind.ALBUM)

    assert query.kind is EntityKind.ALBUM


def test_flag_contradicting_url_is_rejected() -> None:
    with pytest.raises(InvalidQueryError, match="points to a album"):
        parse_query("https://burial.bandcamp.com/album/untrue", EntityKind.TRACK)


def test_matching_flag_is_accepted() -> None:
    query = parse_query("https://burial.bandcamp.com/album/untrue", EntityKind.ALBUM)

    assert query.kind is EntityKind.ALBUM


@pytest.mark.parametrize("url", ["ftp://example.com/x", "https://"])
def test_non_http_url_is_rejected(url: str) -> None:
    with pytest.raises(InvalidQueryError, match="HTTP"):
        parse_query(url)


def test_text_query_is_split() -> None:
    query = parse_query("  Burial - Archangel ", EntityKind.TRACK)

    assert (query.artist, query.title, query.url) == ("Burial", "Archangel", None)


def test_text_query_takes_an_isrc() -> None:
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK, isrc=" gb-aye 97 01376")

    assert query.ids == {IdKind.ISRC: "GBAYE9701376"}


def test_url_query_keeps_its_ids_and_adds_the_isrc() -> None:
    query = parse_query("https://open.spotify.com/track/1", isrc="GBAYE9701376")

    assert query.ids == {IdKind.SPOTIFY: "1", IdKind.ISRC: "GBAYE9701376"}


@pytest.mark.parametrize(
    ("text", "kind", "isrc", "message"),
    [
        ("Radiohead - Paranoid Android", EntityKind.TRACK, "GBAYE97", "not an ISRC"),
        ("Radiohead - OK Computer", EntityKind.ALBUM, "GBAYE9701376", "identifies a track"),
        ("https://open.spotify.com/album/1", None, "GBAYE9701376", "identifies a track"),
    ],
)
def test_bad_isrc_is_an_invalid_query(
    text: str,
    kind: EntityKind | None,
    isrc: str,
    message: str,
) -> None:
    with pytest.raises(InvalidQueryError, match=message):
        parse_query(text, kind, isrc=isrc)
