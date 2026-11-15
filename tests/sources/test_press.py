import pytest

from deadwax import EntityKind, TextKind
from deadwax.core import RecordKey
from deadwax.sources.press import _review


@pytest.mark.parametrize(
    ("url", "selector", "publication"),
    [
        ("https://pitchfork.com/reviews/albums/example/", "body__inner-container", "Pitchfork"),
        ("https://thequietus.com/reviews/example/", "article-content", "The Quietus"),
        ("https://www.thewire.co.uk/in-writing/example", "article-body", "The Wire"),
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
