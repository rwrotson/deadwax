import pytest

from deadwax.core import (
    fold,
    normalize_artist,
    normalize_barcode,
    normalize_code,
    normalize_copyright,
    normalize_text,
    split_featuring,
)
from deadwax.core.normalize import split_artists


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Beyoncé", "beyonce"),
        ("Sigur Rós", "SIGUR ROS"),
        ("Mø", "mo"),
        ("Motörhead", "Motorhead"),
        ("Simon & Garfunkel", "simon and garfunkel"),
        ("AC/DC", "ac dc"),
        ("Don\u2019t Stop", "don't stop"),
        ("\uff21\uff22\uff23", "abc"),
        ("Hello,   World!", "hello world"),
    ],
)
def test_normalize_text_equates_spelling_variants(left: str, right: str) -> None:
    assert normalize_text(left) == normalize_text(right)


def test_cyrillic_letters_keep_their_marks() -> None:
    assert normalize_text("Мой Йошкар-Ола") == "мой йошкар ола"
    assert normalize_text("Ёлка") != normalize_text("Елка")


def test_japanese_text_is_kept_and_width_folded() -> None:
    assert normalize_text("ﾊﾟﾌｭｰﾑ") == normalize_text("パフューム")
    assert normalize_text("細野晴臣") == "細野晴臣"


def test_fold_unifies_dashes_and_quotes() -> None:
    assert fold("A\u2013B “C”") == "a-b 'c'"


@pytest.mark.parametrize(
    ("text", "base", "featured"),
    [
        ("Song (feat. Artist)", "Song", ["Artist"]),
        ("Song [ft. A & B] (Remix)", "Song (Remix)", ["A & B"]),
        ("Main Artist featuring Guest", "Main Artist", ["Guest"]),
        ("Daft Punk", "Daft Punk", []),
        ("Soft Cell", "Soft Cell", []),
    ],
)
def test_split_featuring(text: str, base: str, featured: list[str]) -> None:
    assert split_featuring(text) == (base, featured)


@pytest.mark.parametrize(
    ("left", "right"),
    [("The Beatles", "Beatles"), ("Burial feat. Kode9", "Burial"), ("THE  the", "the")],
)
def test_normalize_artist(left: str, right: str) -> None:
    assert normalize_artist(left) == normalize_artist(right)


def test_lone_the_is_kept() -> None:
    assert normalize_artist("The") == "the"


def test_split_artists() -> None:
    assert split_artists(normalize_text("Burial & Four Tet x Thom Yorke")) == [
        "burial",
        "four tet",
        "thom yorke",
    ]


def test_codes_and_barcodes() -> None:
    assert normalize_code("gb-aaa 07 00001") == "GBAAA0700001"
    assert normalize_code("HDBCD001") == normalize_code("hdbcd 001")
    assert normalize_barcode("5 055300 315829") == normalize_barcode("05055300315829")


def test_copyright_lines() -> None:
    assert normalize_copyright("℗ 2007 Hyperdub Ltd.") == normalize_copyright(
        "(P) 2007 hyperdub ltd",
    )
    assert normalize_copyright("© 2007 Hyperdub") == normalize_copyright("Copyright 2007 Hyperdub")
    assert normalize_copyright("℗ 2007 Hyperdub") != normalize_copyright("© 2007 Hyperdub")
    assert normalize_copyright("2007 Hyperdub") == "|2007 hyperdub"
