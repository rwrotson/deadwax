import pytest

from deadwax import EntityKind, MetricKind, RelationKind, TagKind, TextKind
from deadwax.core import RecordKey, SourceError
from deadwax.sources._http import HttpResources
from deadwax.sources.config import Escalation, SourcesConfig
from deadwax.sources.rateyourmusic import RateYourMusicAdapter


def test_album_page_extracts_facts() -> None:
    adapter = RateYourMusicAdapter(SourcesConfig(), HttpResources())
    html = b"""
    <h1 class="album_title">OK Computer</h1><div class="album_artist"><a>Radiohead</a></div>
    <div class="release_pri_genres"><a>Art Rock</a></div>
    <div class="release_sec_genres"><a>Alternative Rock</a></div>
    <div class="release_descriptors"><a>melancholic</a></div>
    <span class="avg_rating">4.23</span><span class="num_ratings">53,021 ratings</span>
    <div class="chart_peak"><a href="/charts/top/album/1997/">#1 for 1997</a></div>
    <div class="review"><a href="/review/id/">review</a><span class="review_author">Listener</span>
    <div class="review_body">A detailed review.</div></div>
    """
    result = adapter.read_page(
        html,
        "https://rateyourmusic.com/release/album/radiohead/ok-computer/",
        None,
    )
    assert result.candidate is not None
    assert result.candidate.kind is EntityKind.ALBUM
    assert [tag.kind for tag in result.tags] == [
        TagKind.GENRE,
        TagKind.SECONDARY_GENRE,
        TagKind.DESCRIPTOR,
    ]
    assert [metric.kind for metric in result.metrics] == [
        MetricKind.USER_SCORE,
        MetricKind.RATING_VOTES,
    ]
    assert result.metrics[1].value == 53021
    assert result.relations[0].kind is RelationKind.CHARTED_IN
    assert result.texts[0].kind is TextKind.USER
    assert result.texts[0].sources[0].url == "https://rateyourmusic.com/review/id/"


def test_search_and_missing_identity() -> None:
    adapter = RateYourMusicAdapter(SourcesConfig(), HttpResources())
    key = RecordKey(artist="Radiohead", title="OK Computer", kind=EntityKind.ALBUM)
    assert adapter.search_request(key)[1]["searchtype"] == "l"
    hits = adapter.search_hits(
        b'<div class="search_result"><span class="artist">Radiohead</span>'
        b'<a href="/release/album/radiohead/ok-computer/">OK Computer</a></div>',
        "https://rateyourmusic.com/search",
    )
    assert hits[0].key == key
    with pytest.raises(SourceError):
        adapter.read_page(b"<html></html>", "https://rateyourmusic.com/release/album/x/y/", None)


def test_browser_is_first_and_url_kind() -> None:
    from deadwax.core.query import parse_query  # noqa: PLC0415 -- test checks URL parsing

    config = SourcesConfig()
    assert config.html_transports("rateyourmusic") == (Escalation.BROWSER,)
    assert (
        parse_query("https://rateyourmusic.com/release/album/radiohead/ok-computer/").kind
        is EntityKind.ALBUM
    )
