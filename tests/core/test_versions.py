import pytest

from deadwax.core import VersionKind, classify_marker, parse_title


@pytest.mark.parametrize(
    ("title", "base", "kind", "detail"),
    [
        ("Paranoid Android", "Paranoid Android", VersionKind.ORIGINAL, None),
        ("Missing (Todd Terry Remix)", "Missing", VersionKind.REMIX, "Todd Terry Remix"),
        ("Missing - Todd Terry Club Mix", "Missing", VersionKind.REMIX, "Todd Terry Club Mix"),
        ("Track (Original Mix)", "Track", VersionKind.ORIGINAL, "Original Mix"),
        ("Track [Radio Edit]", "Track", VersionKind.EDIT, "Radio Edit"),
        ("Track (Extended Mix)", "Track", VersionKind.EDIT, "Extended Mix"),
        ("Song - Live at Leeds", "Song", VersionKind.LIVE, "Live at Leeds"),
        ("Song (Demo)", "Song", VersionKind.DEMO, "Demo"),
        ("Song - 2011 Remaster", "Song", VersionKind.REMASTER, "2011 Remaster"),
        ("Song (Remastered) [Live]", "Song", VersionKind.LIVE, "Live"),
        ("Song (Live 2011 Remaster)", "Song", VersionKind.LIVE, "Live 2011 Remaster"),
        ("Song (Instrumental)", "Song", VersionKind.INSTRUMENTAL, "Instrumental"),
        ("Song (Unplugged)", "Song", VersionKind.ACOUSTIC, "Unplugged"),
        ("Song (Cover)", "Song", VersionKind.COVER, "Cover"),
        ("Song (Alternate Take)", "Song", VersionKind.ALTERNATE, "Alternate Take"),
        ("Song (Mono)", "Song", VersionKind.ALTERNATE, "Mono"),
        ("Untrue (Deluxe Edition)", "Untrue", VersionKind.REISSUE, "Deluxe Edition"),
        ("Song (Album Version)", "Song", VersionKind.ORIGINAL, "Album Version"),
        ("Stronger (Explicit)", "Stronger", VersionKind.ORIGINAL, "Explicit"),
        ("Stronger [Clean]", "Stronger", VersionKind.EDIT, "Clean"),
        ("Something (Part 1)", "Something (Part 1)", VersionKind.ORIGINAL, None),
        ("Act 1 - Prologue", "Act 1 - Prologue", VersionKind.ORIGINAL, None),
        ("Группа крови", "Группа крови", VersionKind.ORIGINAL, None),
        ("(Remix)", "(Remix)", VersionKind.REMIX, "Remix"),
    ],
)
def test_parse_title(title: str, base: str, kind: VersionKind, detail: str | None) -> None:
    parsed = parse_title(title)

    assert (parsed.base, parsed.version.kind, parsed.version.detail) == (base, kind, detail)


def test_parse_title_collects_featured_artists() -> None:
    parsed = parse_title("Song (feat. Guest) [Live]")

    assert parsed.featured == ["Guest"]
    assert parsed.base == "Song"


@pytest.mark.parametrize("marker", ["Part 2", "Interlude", "Bonus Track", "2007"])
def test_unrelated_markers_are_not_versions(marker: str) -> None:
    assert classify_marker(marker) is None
