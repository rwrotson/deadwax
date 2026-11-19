from pathlib import Path

import pytest

from deadwax.core import SourceError
from deadwax.sources.adapters.norman import parse

PRODUCT = Path(__file__).resolve().parents[3] / "fixtures" / "norman" / "pages" / "untrue.html"


def test_norman_product_facts_without_invented_review() -> None:
    partial = parse.page_partial(
        PRODUCT.read_bytes(),
        "https://www.normanrecords.com/records/94267-burial-untrue",
    )

    assert partial.candidate is not None
    assert (partial.candidate.artist, partial.candidate.title) == ("Burial", "Untrue")
    assert any("Dubstep" in tag.name for tag in partial.tags)
    assert partial.texts == []


def test_norman_rejects_incomplete_page() -> None:
    with pytest.raises(SourceError, match="names no release"):
        parse.page_partial(b"<title>Just a moment...</title>", "https://www.normanrecords.com/x")
