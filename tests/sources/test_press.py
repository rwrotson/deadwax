import httpx
import pytest

from deadwax import EntityKind, HttpSettings, Provenance, Query, ReviewLink, SourcesConfig, TextKind
from deadwax.core import BlockedError, LookupContext, RecordKey
from deadwax.sources._http import HttpResources
from deadwax.sources.press import PressAdapter, _review


@pytest.mark.parametrize(
    ("url", "selector", "publication"),
    [
        ("https://pitchfork.com/reviews/albums/example/", "body__inner-container", "Pitchfork"),
        ("https://thequietus.com/reviews/example/", "article-content", "The Quietus"),
    ],
)
def test_press_page(url: str, selector: str, publication: str) -> None:
    page = f"""
    <h1>Untrue</h1><span class="artist">Burial</span>
    <div class="{selector}"><p>First paragraph.</p><p>Second paragraph.</p></div>
    <a rel="author">A Critic</a><meta itemprop="ratingValue" content="8.5">
    """.encode()
    key = RecordKey(kind=EntityKind.ALBUM, artist="Burial", title="Untrue")

    result = _review(page, url, key)

    assert result is not None
    candidate, review = result
    assert candidate.title == "Untrue"
    assert review.kind is TextKind.REVIEW
    assert review.body == "First paragraph.\n\nSecond paragraph."
    assert review.publication == publication
    assert review.sources[0].url == url


def test_press_rejects_other_version() -> None:
    page = (
        b"<h1>Untrue (Live)</h1><span class='artist'>Burial</span><article><p>Review.</p></article>"
    )
    key = RecordKey(kind=EntityKind.ALBUM, artist="Burial", title="Untrue")

    assert _review(page, "https://pitchfork.com/reviews/albums/example/", key) is None


def test_current_pitchfork_markup() -> None:
    page = b"""
    <h1 data-testid="ContentHeaderHed">Amnesiac</h1>
    <ul class="SplitScreenContentHeaderArtistWrapper-jwNVF"><li>Radiohead</li></ul>
    <div class="body__inner-container"><p>A full review paragraph.</p></div>
    <script>window.__PRELOADED_STATE__ = {"transformed":{"review":{
    "headerProps":{"musicRating":{"score":9}}}}};</script>
    """
    key = RecordKey(kind=EntityKind.ALBUM, artist="Radiohead", title="Amnesiac")

    result = _review(page, "https://pitchfork.com/reviews/albums/6659-amnesiac/", key)

    assert result is not None
    assert result[1].body == "A full review paragraph."
    assert result[1].rating is not None
    assert result[1].rating.value == 9


def test_current_quietus_markup() -> None:
    page = """
    <h1 class="page-title">Rival Dreamer: Burial\u2019s Tunes, 2011 to 2019</h1>
    <div class="entry-content"><p>A full review paragraph.</p></div>
    """.encode()
    key = RecordKey(kind=EntityKind.ALBUM, artist="Burial", title="Tunes 2011 to 2019")

    result = _review(
        page,
        "https://thequietus.com/quietus-reviews/album-of-the-week/example/",
        key,
    )

    assert result is not None
    assert result[1].body == "A full review paragraph."


def test_current_wire_markup() -> None:
    page = b"""
    <article class="article"><h1>Hen Ogledd reviewed</h1><div class="body">
    <p><strong>Hen Ogledd<br></strong><em>Discombobulated<br></em>Domino CD</p>
    <p>A full review paragraph.</p>
    <p>This review appears in The Wire 505.</p>
    </div><footer><div class="contributor-bylines"><a>Abi Bliss</a></div></footer></article>
    """
    key = RecordKey(kind=EntityKind.ALBUM, artist="Hen Ogledd", title="Discombobulated")

    result = _review(
        page,
        "https://www.thewire.co.uk/in-writing/essays/hen-ogledd-reviewed",
        key,
    )

    assert result is not None
    assert result[1].body == "A full review paragraph."
    assert result[1].author == "Abi Bliss"


@pytest.mark.asyncio
async def test_blocked_press_page() -> None:
    url = "https://pitchfork.com/reviews/albums/example/"
    query = Query(kind=EntityKind.ALBUM, artist="Burial", title="Untrue")
    context = LookupContext(
        query=query,
        review_links=[ReviewLink(url=url, sources=[Provenance(source="test", url=url)])],
    )
    config = SourcesConfig(http=HttpSettings(escalation=(), retries=0))
    transport = httpx.MockTransport(
        lambda _: httpx.Response(403, text="<title>Just a moment...</title>"),
    )
    adapter = PressAdapter(config, HttpResources(transport=transport))

    try:
        with pytest.raises(BlockedError):
            await adapter.lookup(query, context)
    finally:
        await adapter.aclose()
