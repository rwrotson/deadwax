import pytest

from deadwax.core import EntityKind, IdKind, InvalidQueryError, Query, parse_query, recognize_url

MBID = "0bb4fdaa-e4f6-4a6b-8d0a-9c5a7e44fd6a"


@pytest.mark.parametrize(
    ("text", "artist", "title"),
    [
        ("Burial - Archangel", "Burial", "Archangel"),
        ("Burial \u2013 Archangel", "Burial", "Archangel"),
        ("Burial — Archangel", "Burial", "Archangel"),
        ('"Jay-Z - 99 Problems"', "Jay-Z", "99 Problems"),
        ("Кино - «Группа крови»", "Кино", "Группа крови"),
        ("  細野晴臣 - Hosono House  ", "細野晴臣", "Hosono House"),
        ("Artist - Title - Live", "Artist", "Title - Live"),
    ],
)
def test_text_query_splits_artist_and_title(text: str, artist: str, title: str) -> None:
    query = parse_query(text, EntityKind.TRACK)

    assert (query.kind, query.artist, query.title, query.url) == (
        EntityKind.TRACK,
        artist,
        title,
        None,
    )


@pytest.mark.parametrize(
    "text",
    ["", "   ", "Burial", "Burial -", "- Archangel", "Jay-Z", 'Burial - ""'],
)
def test_text_query_without_artist_and_title_is_rejected(text: str) -> None:
    with pytest.raises(InvalidQueryError):
        parse_query(text, EntityKind.TRACK)


def test_text_query_requires_kind() -> None:
    with pytest.raises(InvalidQueryError, match="album or a track"):
        parse_query("Burial - Archangel")


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
    ],
)
def test_url_kind_and_ids_are_recognized(
    url: str,
    kind: EntityKind | None,
    ids: dict[IdKind, str],
) -> None:
    assert recognize_url(url) == (kind, ids)

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


def test_query_model_requires_artist_and_title_or_url() -> None:
    with pytest.raises(ValueError, match="artist and a title"):
        Query(kind=EntityKind.TRACK, artist="Burial")


def test_query_model_requires_kind_for_text() -> None:
    with pytest.raises(ValueError, match="album or a track"):
        Query(artist="Burial", title="Archangel")


def test_invalid_query_error_is_a_value_error() -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - the base class is what callers catch.
        parse_query("Burial")
