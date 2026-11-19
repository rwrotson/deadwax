import httpx
import pytest

from deadwax import EntityKind, ErrorKind, MetricKind, Query, RelationKind, TagKind, TextKind
from deadwax.core import RecordKey, SourceError
from deadwax.sources._http import HttpResources
from deadwax.sources.adapters.rateyourmusic import RateYourMusicAdapter
from deadwax.sources.config import Escalation, SourcesConfig, SourceSettings
from deadwax.sources.lookup import lookup


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
    assert result.relations[0].target.name == "1997"
    assert result.relations[0].note == "#1"
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("search_body", "page_body", "error", "other_version"),
    [
        (b"<html></html>", b"", ErrorKind.NOT_FOUND, False),
        (
            b"<title>Just a moment...</title><div id='cf-browser-verification'></div>",
            b"",
            ErrorKind.BLOCKED,
            False,
        ),
        (
            b'<div class="search_result"><span class="artist">Radiohead</span>'
            b'<a href="/release/album/radiohead/ok-computer-extended/">'
            b"OK Computer (Extended Mix)</a></div>",
            b'<h1 class="album_title">OK Computer (Extended Mix)</h1>'
            b'<div class="album_artist">Radiohead</div>'
            b'<div class="release_pri_genres"><a>Art Rock</a></div>',
            None,
            True,
        ),
    ],
)
async def test_lookup_failure_and_version_gate(
    search_body: bytes,
    page_body: bytes,
    error: ErrorKind | None,
    other_version: bool,
) -> None:
    config = SourcesConfig(
        rateyourmusic=SourceSettings(html_transports=(Escalation.HTTPX,)),
    )

    def respond(request: httpx.Request) -> httpx.Response:
        content = page_body if "/release/" in request.url.path else search_body
        status = 403 if error is ErrorKind.BLOCKED else 200
        return httpx.Response(status, content=content)

    dossier = await lookup(
        Query(kind=EntityKind.ALBUM, artist="Radiohead", title="OK Computer"),
        config,
        include=["rateyourmusic"],
        transport=httpx.MockTransport(respond),
    )
    if error is not None:
        assert dossier.errors[0].kind is error
    if other_version:
        assert not dossier.tags
        assert any(relation.kind is RelationKind.OTHER_VERSION for relation in dossier.relations)
