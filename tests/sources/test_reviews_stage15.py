from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from deadwax import EntityKind, MetricKind, Query, Rating, ReviewLink, Scope, Text, TextKind
from deadwax.core import Partial, Provenance, RecordCandidate, SourceError, merge
from deadwax.sources.albumoftheyear import AlbumOfTheYearAdapter
from deadwax.sources.allmusic import AllMusicAdapter

ALLMUSIC_PAGES = Path(__file__).resolve().parent.parent / "fixtures" / "allmusic" / "pages"
AOTY_PAGES = Path(__file__).resolve().parent.parent / "fixtures" / "albumoftheyear" / "pages"


def test_albumoftheyear_real_page_structure() -> None:
    adapter = object.__new__(AlbumOfTheYearAdapter)
    hits = adapter.search_hits(
        (AOTY_PAGES / "search_ok_computer.html").read_bytes(),
        "https://www.albumoftheyear.org/search/?q=Radiohead+OK+Computer",
    )
    result = adapter.read_page(
        (AOTY_PAGES / "ok_computer.html").read_bytes(),
        "https://www.albumoftheyear.org/album/362-radiohead-ok-computer.php",
        None,
    )

    assert (hits[0].key.artist, hits[0].key.title) == ("Radiohead", "OK Computer")
    assert result.candidate is not None
    assert (result.candidate.artist, result.candidate.title) == ("Radiohead", "OK Computer")
    assert len(result.texts) == 16
    assert result.metrics[0].kind is MetricKind.USER_SCORE
    assert result.metrics[0].value == 93
    assert {tag.name for tag in result.tags} >= {"Alternative Rock", "Art Rock"}
    assert any(link.publication == "Pitchfork" for link in result.review_links)


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


def test_albumoftheyear_page_extracts_scores_and_review_link() -> None:
    html = b"""
    <h1 class="albumTitle">OK Computer</h1><div class="artistTitle">Radiohead</div>
    <div class="criticReview"><span class="publication">Pitchfork</span>
    <span class="score">95</span><a href="https://pitchfork.com/reviews/albums/ok-computer/">Read</a></div>
    <div class="userScore">93</div><div class="genre"><a>Art Rock</a></div>
    """
    adapter = object.__new__(AlbumOfTheYearAdapter)
    result = adapter.read_page(html, "https://www.albumoftheyear.org/album/ok-computer.php", None)
    assert result.texts[0].publication == "Pitchfork"
    assert result.texts[0].rating == Rating(value=95, scale=100)
    assert result.metrics[0].kind is MetricKind.USER_SCORE
    assert result.metrics[0].value == 93
    assert result.review_links[0].url.startswith("https://pitchfork.com/")


def test_review_score_merges_and_rejected_links_do_not_leak() -> None:
    query = Query(kind=EntityKind.ALBUM, artist="Radiohead", title="OK Computer")
    candidate = RecordCandidate(kind=EntityKind.ALBUM, artist="Radiohead", title="OK Computer")
    source = Provenance(source="allmusic", url="https://www.allmusic.com/album/ok-computer")
    wiki = Provenance(source="wikipedia", url="https://en.wikipedia.org/wiki/OK_Computer")
    review = Text(
        kind=TextKind.REVIEW,
        body="A textured guitar record.",
        publication="AllMusic",
        rating=Rating(value=4.5, scale=5),
        scope=Scope.RELEASE_GROUP,
        sources=[source],
    )
    score = review.model_copy(update={"body": "", "sources": [wiki]})
    other = RecordCandidate(kind=EntityKind.ALBUM, artist="Radiohead", title="OK Computer (Live)")
    dossier = merge(
        query,
        [
            Partial(source="wikipedia", candidate=candidate, texts=[score]),
            Partial(source="allmusic", candidate=candidate, texts=[review]),
            Partial(
                source="albumoftheyear",
                candidate=other,
                review_links=[ReviewLink(url="https://pitchfork.com/other", sources=[source])],
            ),
        ],
        generated_at=datetime(2026, 11, 14, tzinfo=UTC),
    )
    assert len(dossier.texts) == 1
    assert {item.source for item in dossier.texts[0].sources} == {"wikipedia", "allmusic"}
    assert dossier.review_links == []


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
