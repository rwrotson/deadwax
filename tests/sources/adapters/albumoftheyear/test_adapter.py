from pathlib import Path

import httpx
import pytest

from deadwax import (
    EntityKind,
    MetricKind,
    Query,
    Rating,
    RelationKind,
    Scope,
)
from deadwax.core import (
    NotFoundError,
    RecordKey,
)
from deadwax.sources.adapters.albumoftheyear import AlbumOfTheYearAdapter
from deadwax.sources.config import Escalation, SourcesConfig, SourceSettings
from deadwax.sources.lookup import lookup

AOTY_PAGES = Path(__file__).resolve().parents[3] / "fixtures" / "albumoftheyear" / "pages"


THERE_THERE = "https://www.albumoftheyear.org/album/54781-radiohead-there-there.php"


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


def test_albumoftheyear_single_page_gives_the_track_on_its_release() -> None:
    adapter = object.__new__(AlbumOfTheYearAdapter)
    key = RecordKey("Radiohead", "There There", EntityKind.TRACK)

    result = adapter.read_page(
        (AOTY_PAGES / "there_there_single.html").read_bytes(),
        THERE_THERE,
        key,
    )

    assert result.candidate is not None
    assert (result.candidate.kind, result.candidate.artist, result.candidate.title) == (
        EntityKind.TRACK,
        "Radiohead",
        "There, There",
    )
    [relation] = result.relations
    assert (relation.kind, relation.target.name) == (RelationKind.APPEARS_ON, "There, There")
    assert all(tag.scope is Scope.RELEASE_GROUP for tag in result.tags)


def test_albumoftheyear_release_without_the_track_is_not_found() -> None:
    adapter = object.__new__(AlbumOfTheYearAdapter)
    key = RecordKey("Radiohead", "Creep", EntityKind.TRACK)

    with pytest.raises(NotFoundError, match="does not list the track"):
        adapter.read_page((AOTY_PAGES / "there_there_single.html").read_bytes(), THERE_THERE, key)


@pytest.mark.asyncio
async def test_albumoftheyear_track_query_finds_its_single() -> None:
    search = (
        '<div class="albumBlock"><a href="/album/54781-radiohead-there-there.php">'
        '<div class="albumTitle">There, There</div></a>'
        '<div class="artistTitle">Radiohead</div></div>'
    )
    single = (AOTY_PAGES / "there_there_single.html").read_bytes()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/":
            return httpx.Response(200, text=search)
        return httpx.Response(200, content=single)

    dossier = await lookup(
        Query(kind=EntityKind.TRACK, artist="Radiohead", title="There There"),
        SourcesConfig(albumoftheyear=SourceSettings(html_transports=(Escalation.HTTPX,))),
        include=["albumoftheyear"],
        transport=httpx.MockTransport(respond),
    )

    assert dossier.errors == []
    assert any(relation.target.url == THERE_THERE for relation in dossier.relations)
