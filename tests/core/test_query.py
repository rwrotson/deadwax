import re

import pytest
from pydantic import TypeAdapter, ValidationError

from deadwax.core import (
    AlbumQuery,
    ArtistQuery,
    EntityKind,
    IdKind,
    InvalidQueryError,
    LabelQuery,
    Query,
    TrackQuery,
    UnresolvedQuery,
    UrlRule,
    isrc_code,
    recognize_url,
    text_query,
    url_query,
    with_kind,
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

    assert isinstance(query, TrackQuery)
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
    with pytest.raises(InvalidQueryError, match="track, album, artist, or label"):
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
        TrackQuery(artist="Burial")


def test_query_without_kind_needs_a_url() -> None:
    with pytest.raises(ValidationError, match="url"):
        TypeAdapter(Query).validate_python({"artist": "Burial", "title": "Archangel"})


def test_invalid_query_error_is_a_value_error() -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - the base class is what callers catch.
        text_query("Burial", EntityKind.TRACK)


@pytest.mark.parametrize(
    ("code", "normalized"),
    [
        ("GBAYE9701376", "GBAYE9701376"),
        (" gb-aye-97-01376 ", "GBAYE9701376"),
        ("us.rc1.76.07839", "USRC17607839"),
    ],
)
def test_isrc_code_normalizes(code: str, normalized: str) -> None:
    assert isrc_code(code) == normalized


@pytest.mark.parametrize(
    "code",
    ["", "GBAYE97013", "GBAYE97013765", "12AYE9701376", "GBAYE97O1376"],
)
def test_malformed_isrc_is_rejected(code: str) -> None:
    with pytest.raises(InvalidQueryError, match="not an ISRC"):
        isrc_code(code)


def test_text_query_takes_an_isrc() -> None:
    query = text_query("Radiohead - Paranoid Android", EntityKind.TRACK, isrc="gb-aye-97-01376")

    assert query.ids == {IdKind.ISRC: "GBAYE9701376"}


def test_text_query_rejects_an_isrc_for_an_album() -> None:
    with pytest.raises(InvalidQueryError, match="identifies a track"):
        text_query("Radiohead - OK Computer", EntityKind.ALBUM, isrc="GBAYE9701376")


def test_query_model_normalizes_its_isrc() -> None:
    query = TrackQuery(
        artist="Radiohead",
        title="Paranoid Android",
        ids={IdKind.ISRC: "gbaye9701376"},
    )

    assert query.ids[IdKind.ISRC] == "GBAYE9701376"


def test_query_model_rejects_a_malformed_isrc() -> None:
    with pytest.raises(ValueError, match="not an ISRC"):
        UnresolvedQuery(url="https://example.com/x", ids={IdKind.ISRC: "GBAYE97"})


def test_query_model_rejects_an_isrc_for_an_album() -> None:
    with pytest.raises(ValueError, match="identifies a track"):
        AlbumQuery(url="https://example.com/x", ids={IdKind.ISRC: "GBAYE9701376"})


@pytest.mark.parametrize(
    ("text", "kind", "expected"),
    [
        ("  Aphex Twin ", EntityKind.ARTIST, ArtistQuery(name="Aphex Twin")),
        ("Sly & Robbie - Dub", EntityKind.ARTIST, ArtistQuery(name="Sly & Robbie - Dub")),
        ("«Мелодия»", EntityKind.LABEL, LabelQuery(name="Мелодия")),
        ("Burial - Untrue", EntityKind.ALBUM, AlbumQuery(artist="Burial", title="Untrue")),
    ],
)
def test_text_query_of_each_kind(text: str, kind: EntityKind, expected: Query) -> None:
    assert text_query(text, kind) == expected


def test_a_name_query_needs_a_name_or_url() -> None:
    with pytest.raises(InvalidQueryError, match="empty"):
        text_query('""', EntityKind.LABEL)
    with pytest.raises(ValidationError, match="name or a URL"):
        ArtistQuery()

    assert LabelQuery(url="https://example.org/label").name is None


@pytest.mark.parametrize("kind", [EntityKind.ALBUM, EntityKind.ARTIST, EntityKind.LABEL])
def test_only_a_track_takes_an_isrc(kind: EntityKind) -> None:
    article = "a" if kind is EntityKind.LABEL else "an"

    with pytest.raises(InvalidQueryError, match=f"not {article} {kind}"):
        text_query("Burial - Archangel", kind, isrc="GBAYE9701376")
    with pytest.raises(ValidationError, match=f"not {article} {kind}"):
        url_query("https://example.org/x", kind, {IdKind.ISRC: "GBAYE9701376"})


def test_queries_are_told_apart_by_kind() -> None:
    adapter: TypeAdapter[Query] = TypeAdapter(Query)

    assert isinstance(adapter.validate_python({"kind": "label", "name": "Warp"}), LabelQuery)
    assert isinstance(adapter.validate_python({"kind": "artist", "name": "AFX"}), ArtistQuery)
    assert isinstance(adapter.validate_python({"url": "https://example.org/x"}), UnresolvedQuery)
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "work", "name": "X"})


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (EntityKind.TRACK, TrackQuery(url="https://e/x", ids={IdKind.ISRC: "GBAYE9701376"})),
        (EntityKind.ALBUM, AlbumQuery(url="https://e/x")),
        (EntityKind.ARTIST, ArtistQuery(url="https://e/x")),
        (EntityKind.LABEL, LabelQuery(url="https://e/x")),
        (None, UnresolvedQuery(url="https://e/x", ids={IdKind.ISRC: "GBAYE9701376"})),
    ],
)
def test_with_kind_promotes_a_url_query_and_drops_a_misfit_isrc(
    kind: EntityKind | None,
    expected: Query,
) -> None:
    query = UnresolvedQuery(url="https://e/x", ids={IdKind.ISRC: "GBAYE9701376"})

    assert with_kind(query, kind) == expected


def test_with_kind_keeps_a_query_of_known_kind() -> None:
    query = TrackQuery(artist="Burial", title="Archangel")

    assert with_kind(query, EntityKind.ALBUM) is query


def test_url_query_of_unknown_kind_is_unresolved() -> None:
    assert url_query("https://e/x", None, {}) == UnresolvedQuery(url="https://e/x")
