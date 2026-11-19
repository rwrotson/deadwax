from pathlib import Path

import pytest

from deadwax.core import EntityKind, RecordKey, SourceError, TextKind
from deadwax.sources._search import pick_hit
from deadwax.sources.adapters.bleep.parse import page_partial as bleep_page
from deadwax.sources.adapters.bleep.parse import search_hits as bleep_hits

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


def test_bleep_saved_pages() -> None:
    key = RecordKey(artist="Burial", title="Untrue", kind=EntityKind.ALBUM)
    search = (FIXTURES / "bleep/pages/search_untrue.html").read_bytes()
    picked = pick_hit(key, bleep_hits(search))
    assert picked is not None
    assert picked.url.endswith("-burial-untrue")

    page = (FIXTURES / "bleep/pages/untrue.html").read_bytes()
    partial = bleep_page(page, "https://bleep.com/release/288787-burial-untrue", key)
    assert partial.candidate is not None
    assert partial.candidate.title == "Untrue"
    assert partial.candidate.date == "2007-11-05"
    assert partial.texts[0].kind is TextKind.SHOP
    assert "Archangel" in partial.texts[0].body
    assert {tag.name for tag in partial.tags} == {"Bass", "Dubstep"}


def test_bleep_missing_page() -> None:
    with pytest.raises(SourceError):
        bleep_page(b"<html></html>", "https://bleep.com/release/missing", None)
