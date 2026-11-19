import re

import pytest

from deadwax.core import (
    EntityKind,
    IdKind,
    InvalidQueryError,
    Query,
    UrlRule,
    recognize_url,
    text_query,
)


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
    query = text_query(text, EntityKind.TRACK)

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
        text_query(text, EntityKind.TRACK)


def test_text_query_requires_kind() -> None:
    with pytest.raises(InvalidQueryError, match="album or a track"):
        text_query("Burial - Archangel", None)


RULES = (
    UrlRule(re.compile(r"^/song/(?P<id>\d+)"), EntityKind.TRACK, IdKind.DEEZER),
    UrlRule(re.compile(r"^/album/\d+"), EntityKind.TRACK, IdKind.APPLE_MUSIC, param="i"),
    UrlRule(re.compile(r"^/album/"), EntityKind.ALBUM),
)


@pytest.mark.parametrize(
    ("url", "kind", "ids"),
    [
        ("https://example.com/song/7", EntityKind.TRACK, {IdKind.DEEZER: "7"}),
        ("https://example.com/album/1?i=2", EntityKind.TRACK, {IdKind.APPLE_MUSIC: "2"}),
        ("https://example.com/album/1", EntityKind.ALBUM, {}),
        ("https://example.com/album/1?j=2", EntityKind.ALBUM, {}),
        ("https://example.com/artist/1", None, {}),
        ("https://example.com", None, {}),
    ],
)
def test_first_matching_rule_gives_kind_and_ids(
    url: str,
    kind: EntityKind | None,
    ids: dict[IdKind, str],
) -> None:
    assert recognize_url(url, RULES) == (kind, ids)


def test_query_model_requires_artist_and_title_or_url() -> None:
    with pytest.raises(ValueError, match="artist and a title"):
        Query(kind=EntityKind.TRACK, artist="Burial")


def test_query_model_requires_kind_for_text() -> None:
    with pytest.raises(ValueError, match="album or a track"):
        Query(artist="Burial", title="Archangel")


def test_invalid_query_error_is_a_value_error() -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - the base class is what callers catch.
        text_query("Burial", EntityKind.TRACK)
