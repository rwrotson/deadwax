from deadwax import EntityKind, Scope, TextKind
from deadwax.core import RecordKey
from deadwax.sources.residentadvisor import _extract, _review_id


def test_review_link_and_graphql_record() -> None:
    assert _review_id("https://ra.co/reviews/4920") == "4920"
    record: dict[str, object] = {
        "id": "4920",
        "type": "ALBUM",
        "title": "Burial - Untrue",
        "content": "<p>First paragraph.</p><p>Second paragraph.</p>",
        "author": {"name": "Chris Mann"},
        "artists": [{"name": "Burial", "biography": {"blurb": "Artist biography."}}],
        "labels": [{"name": "Hyperdub", "blurb": "Label biography."}],
    }
    key = RecordKey(kind=EntityKind.ALBUM, artist="Burial", title="Untrue")

    result = _extract(record, key, "https://ra.co/reviews/4920")

    assert result is not None
    candidate, texts = result
    assert candidate.artist == "Burial"
    assert [text.scope for text in texts] == [Scope.RELEASE_GROUP, Scope.ARTIST, Scope.LABEL]
    assert texts[0].kind is TextKind.REVIEW
    assert texts[0].author == "Chris Mann"
    assert "First paragraph." in texts[0].body


def test_other_version_and_other_host_are_rejected() -> None:
    assert _review_id("https://elsewhere.example/reviews/4920") is None
    key = RecordKey(kind=EntityKind.ALBUM, artist="Burial", title="Untrue")
    record: dict[str, object] = {
        "type": "ALBUM",
        "title": "Burial - Untrue (Live)",
        "artists": [{"name": "Burial"}],
    }

    assert _extract(record, key, "https://ra.co/reviews/4920") is None
