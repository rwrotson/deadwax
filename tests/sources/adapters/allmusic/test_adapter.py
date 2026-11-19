from collections.abc import Callable
from pathlib import Path

import pytest

from deadwax import (
    Rating,
)
from deadwax.core import (
    SourceError,
)
from deadwax.sources.adapters.allmusic import AllMusicAdapter

ALLMUSIC_PAGES = Path(__file__).resolve().parents[3] / "fixtures" / "allmusic" / "pages"


def test_allmusic_real_page_structure() -> None:
    adapter = object.__new__(AllMusicAdapter)
    hits = adapter.search_hits(
        (ALLMUSIC_PAGES / "search_ok_computer.html").read_bytes(),
        "https://www.allmusic.com/search/albums/OK%20Computer",
    )
    result = adapter.read_page(
        (ALLMUSIC_PAGES / "ok_computer.html").read_bytes(),
        "https://www.allmusic.com/album/ok-computer-mw0000024289",
        None,
    )

    assert (hits[0].key.artist, hits[0].key.title) == ("Radiohead", "OK Computer")
    assert result.candidate is not None
    assert (result.candidate.artist, result.candidate.title) == ("Radiohead", "OK Computer")
    assert result.texts[0].author == "Stephen Thomas Erlewine"
    assert result.texts[0].rating == Rating(value=4.5, scale=5)
    assert {tag.kind for tag in result.tags} == {"style", "mood", "theme"}
    assert result.credits


def test_allmusic_page_extracts_review_and_facets() -> None:
    html = b"""
    <h1 class="album-title">OK Computer</h1><div class="album-artist">Radiohead</div>
    <div class="allmusic-rating" data-rating="4.5"></div>
    <div class="review"><span class="author">Stephen Thomas Erlewine</span>
    <p>A textured guitar record.</p></div>
    <div class="styles"><a>Alternative Rock</a></div>
    <div class="moods"><a>Brooding</a></div>
    <div class="themes"><a>Alienation</a></div>
    <div class="credits"><div class="credit"><span class="name">Nigel Godrich</span>
    <span class="role">Producer</span></div></div>
    <div class="similar-albums"><a class="title" href="/album/kid-a">Kid A</a></div>
    """
    adapter = object.__new__(AllMusicAdapter)
    result = adapter.read_page(html, "https://www.allmusic.com/album/ok-computer", None)
    assert result.texts[0].body == "A textured guitar record."
    assert result.texts[0].rating == Rating(value=4.5, scale=5)
    assert {tag.kind for tag in result.tags} == {"style", "mood", "theme"}
    assert result.credits[0].name == "Nigel Godrich"
    assert result.relations[0].target.name == "Kid A"


def test_unrecognized_allmusic_page_is_traced(
    traced: Callable[[str], list[dict[str, object]]],
) -> None:
    html = b"<html><title>Access check</title><body><p>Please wait</p></body></html>"
    adapter = object.__new__(AllMusicAdapter)

    with pytest.raises(SourceError, match="names no record"):
        adapter.read_page(html, "https://www.allmusic.com/album/x", None)

    [event] = traced("parse.unrecognized")
    assert event["title"] == "Access check"
    assert event["snippet"] == "Please wait"
