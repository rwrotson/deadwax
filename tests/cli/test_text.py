import pytest

from deadwax import Rating, Relation, SourceAccess, VersionInfo, VersionKind
from deadwax.cli.text import access_label, number, rating, relation_details, version_text


@pytest.mark.parametrize(
    ("access", "label"),
    [
        (SourceAccess(), ""),
        (SourceAccess(api=True), "API (httpx)"),
        (SourceAccess(browser_headless=True), "HTML (no permitted transports)"),
        (
            SourceAccess(html_transports=["httpx", "nodriver"], browser_headless=False),
            "HTML (httpx → nodriver [headed])",
        ),
        (
            SourceAccess(
                api=True,
                html_transports=["patchright"],
                browser_headless=True,
                headed_fallback=True,
            ),
            "API (httpx); HTML (patchright [headless → headed])",
        ),
    ],
)
def test_access_label(access: SourceAccess, label: str) -> None:
    assert access_label(access) == label


@pytest.mark.parametrize(
    ("value", "grouped", "text"),
    [(1234567.0, False, "1234567"), (1234567.0, True, "1,234,567"), (8.5, True, "8.5")],
)
def test_number(value: float, grouped: bool, text: str) -> None:
    assert number(value, grouped=grouped) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, ""),
        (Rating(), ""),
        (Rating(value=8.5, scale=10), "8.5/10"),
        (Rating(value=4), "4"),
        (Rating(value=4, scale=5, text="4/5"), "4/5"),
    ],
)
def test_rating(value: Rating | None, text: str) -> None:
    assert rating(value) == text


def test_version_text() -> None:
    assert version_text(VersionInfo()) == "original"
    assert version_text(VersionInfo(kind=VersionKind.REMIX, detail="Dub")) == "remix (Dub)"


def test_relation_details() -> None:
    relation = Relation.model_validate(
        {
            "kind": "samples",
            "target": {"type": "recording", "name": "X"},
            "note": "intro",
            "element": "vocals",
            "recording_offset": 3,
            "target_offset": 0,
            "scope": "recording",
            "sources": [{"source": "whosampled"}],
        },
    )

    assert relation_details(relation) == ["intro", "vocals", "recording 3s", "target 0s"]
