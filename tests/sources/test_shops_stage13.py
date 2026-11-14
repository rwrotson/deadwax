from pathlib import Path

import pytest

from deadwax.core import EntityKind, RecordKey, SourceError, TextKind, Verdict, compare
from deadwax.sources._base import pick_hit
from deadwax.sources.bleep.parse import page_partial as bleep_page
from deadwax.sources.bleep.parse import search_hits as bleep_hits
from deadwax.sources.forcedexposure.parse import page_partial as forced_page
from deadwax.sources.forcedexposure.parse import search_hits as forced_hits

FIXTURES = Path(__file__).parents[1] / "fixtures"


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


def test_forced_exposure_saved_pages() -> None:
    search = (FIXTURES / "forcedexposure/pages/artist_burial.html").read_bytes()
    hits = forced_hits(search)
    assert hits[0].key.artist == "BURIAL"
    assert hits[0].key.title == "Street Halo/Kindred"

    page = (FIXTURES / "forcedexposure/pages/hyperdub_54.html").read_bytes()
    partial = forced_page(
        page,
        "https://www.forcedexposure.com/Catalog/va-hyperdub-5-4-ep-12-/HDB.026EP.html",
    )
    assert partial.candidate is not None
    assert partial.candidate.title == "Hyperdub 5.4 EP"
    assert partial.candidate.date == "2009-10-19"
    assert partial.texts[0].kind is TextKind.LABEL
    assert partial.tags[0].name == "ELECTRONIC"
    assert partial.relations


def test_missing_pages_and_other_version() -> None:
    with pytest.raises(SourceError):
        bleep_page(b"<html></html>", "https://bleep.com/release/missing", None)
    with pytest.raises(SourceError):
        forced_page(b"<html></html>", "https://www.forcedexposure.com/Catalog/missing.html")

    original = RecordKey(artist="Burial", title="Untrue", kind=EntityKind.ALBUM)
    extended = RecordKey(artist="Burial", title="Untrue (Extended Mix)", kind=EntityKind.ALBUM)
    assert compare(original, extended).verdict is Verdict.OTHER_VERSION
