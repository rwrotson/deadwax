from pathlib import Path

import pytest

from deadwax.core import SourceError, TextKind
from deadwax.sources.boomkat import parse

PAGES = Path(__file__).resolve().parent.parent / "fixtures" / "boomkat" / "pages"


def test_boomkat_search_and_product_facts() -> None:
    hits = parse.search_hits((PAGES / "search_untrue.html").read_bytes())
    partial = parse.page_partial((PAGES / "untrue.html").read_bytes(), "https://boomkat.com/old")

    assert len(hits) == 1
    assert (hits[0].key.artist, hits[0].key.title) == ("Burial", "Untrue")
    assert partial.candidate is not None
    assert partial.candidate.url is not None
    assert partial.candidate.url.endswith("untrue-c8630b")
    assert partial.texts[0].kind is TextKind.SHOP
    assert "Dubstep" in [tag.name for tag in partial.tags]


def test_boomkat_rejects_incomplete_page() -> None:
    with pytest.raises(SourceError, match="names no release"):
        parse.page_partial(b"<title>Just a moment...</title>", "https://boomkat.com/x")
