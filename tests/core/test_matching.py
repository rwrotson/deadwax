from collections.abc import Callable

import pytest

from deadwax.core import (
    EntityKind,
    IdKind,
    NameKey,
    RecordKey,
    Verdict,
    VersionInfo,
    VersionKind,
    artist_similarity,
    compare,
    compare_names,
    title_similarity,
)
from deadwax.core.matching import key_similarity, same_version


def track(artist: str, title: str, version: VersionInfo | None = None) -> RecordKey:
    return RecordKey(artist=artist, title=title, kind=EntityKind.TRACK, version=version)


@pytest.mark.parametrize(
    ("candidate", "verdict"),
    [
        (track("Everything But The Girl", "Missing"), Verdict.MATCH),
        (track("everything but the girl", "MISSING"), Verdict.MATCH),
        (track("Everything But the Girl", "Missing (Todd Terry Remix)"), Verdict.OTHER_VERSION),
        (track("Everything But the Girl", "Missing - Live"), Verdict.OTHER_VERSION),
        (track("Everything But the Girl", "Missing - 2013 Remaster"), Verdict.OTHER_VERSION),
        (track("Everything But the Girl", "Missing (Demo)"), Verdict.OTHER_VERSION),
        (track("Some Cover Band", "Missing"), Verdict.NO_MATCH),
        (track("Everything But the Girl", "Driving"), Verdict.NO_MATCH),
    ],
)
def test_original_query_against_candidates(candidate: RecordKey, verdict: Verdict) -> None:
    reference = track("Everything but the Girl", "Missing")

    assert compare(reference, candidate).verdict is verdict


@pytest.mark.parametrize(
    ("candidate", "verdict"),
    [
        (track("Everything but the Girl", "Missing - Todd Terry Remix"), Verdict.MATCH),
        (track("Everything but the Girl", "Missing (Todd Terry Club Mix)"), Verdict.MATCH),
        (track("Everything but the Girl", "Missing"), Verdict.OTHER_VERSION),
        (track("Everything but the Girl", "Missing (Kenny Dope Remix)"), Verdict.OTHER_VERSION),
    ],
)
def test_remix_query_against_candidates(candidate: RecordKey, verdict: Verdict) -> None:
    reference = track("Everything but the Girl", "Missing (Todd Terry Remix)")

    assert compare(reference, candidate).verdict is verdict


@pytest.mark.parametrize(
    ("reference", "candidate", "verdict"),
    [
        ("Track (Original Mix)", "Track", Verdict.MATCH),
        ("Track (Extended Mix)", "Track (Club Mix)", Verdict.MATCH),
        ("Track (Original Mix)", "Track (Extended Mix)", Verdict.OTHER_VERSION),
        ("Track (Radio Edit)", "Track (Extended Mix)", Verdict.OTHER_VERSION),
        ("Track (Dub)", "Track (Original Mix)", Verdict.OTHER_VERSION),
        ("Track (Kode9 Edit)", "Track (Theo Parrish Edit)", Verdict.OTHER_VERSION),
        ("Track (Kode9 Edit)", "Track (Kode9 Re-Edit)", Verdict.MATCH),
        ("Track (Todd Terry Remix)", "Track (Todd Terry Extended Remix)", Verdict.OTHER_VERSION),
        ("Track (Todd Terry Remix)", "Track (Todd Terry Dub)", Verdict.OTHER_VERSION),
        ("Track (Todd Terry Remix)", "Track (Todd Terry Remix - Intro)", Verdict.OTHER_VERSION),
        ("Track (Todd Terry Remix)", "Track (Todd Terry Club Mix)", Verdict.MATCH),
    ],
)
def test_mix_names_tell_versions_apart(reference: str, candidate: str, verdict: Verdict) -> None:
    assert compare(track("Artist", reference), track("Artist", candidate)).verdict is verdict


@pytest.mark.parametrize(
    ("reference", "candidate", "verdict"),
    [
        ("There There", "There There. (The Boney King of Nowhere.)", Verdict.MATCH),
        ("There There. (The Boney King of Nowhere.)", "There There", Verdict.MATCH),
        ("Gimme! Gimme! Gimme!", "Gimme! Gimme! Gimme! (A Man After Midnight)", Verdict.MATCH),
        ("Song", "Song [Another Name for It]", Verdict.MATCH),
        ("Missing", "Missing (Tee Beat)", Verdict.NO_MATCH),
        ("Love Story", "Love Story (Taylor's Version)", Verdict.NO_MATCH),
        ("Song", "Song (Part 2)", Verdict.NO_MATCH),
        ("Song", "Song (Pt. II)", Verdict.NO_MATCH),
        ("Song", "Song (Reprise)", Verdict.NO_MATCH),
        ("Song", "Song (Interlude)", Verdict.NO_MATCH),
        ("Song", "Song (2011)", Verdict.NO_MATCH),
        ("Song", "Song (No. 3)", Verdict.NO_MATCH),
        ("There There (Live)", "There There. (The Boney King of Nowhere.)", Verdict.OTHER_VERSION),
    ],
)
def test_alternative_titles_in_brackets(reference: str, candidate: str, verdict: Verdict) -> None:
    assert compare(track("Radiohead", reference), track("Radiohead", candidate)).verdict is verdict


def test_explicit_candidate_version_overrides_title() -> None:
    reference = track("Radiohead", "Paranoid Android")
    live = track("Radiohead", "Paranoid Android", VersionInfo(kind=VersionKind.LIVE))

    assert compare(reference, live).verdict is Verdict.OTHER_VERSION


def test_live_recordings_from_different_concerts_differ() -> None:
    leeds = VersionInfo(kind=VersionKind.LIVE, detail="Live at Leeds")
    glastonbury = VersionInfo(kind=VersionKind.LIVE, detail="Live at Glastonbury 1997")
    unspecified = VersionInfo(kind=VersionKind.LIVE)

    assert not same_version(leeds, glastonbury)
    assert same_version(leeds, unspecified)
    assert same_version(
        VersionInfo(kind=VersionKind.REMASTER, detail="2009"),
        VersionInfo(kind=VersionKind.REMASTER, detail="2017"),
    )


def test_album_and_track_do_not_match() -> None:
    album = RecordKey(artist="Burial", title="Untrue", kind=EntityKind.ALBUM)
    title_track = RecordKey(artist="Burial", title="Untrue", kind=EntityKind.TRACK)

    assert compare(album, title_track).verdict is Verdict.NO_MATCH
    assert compare(album, RecordKey(artist="Burial", title="Untrue")).verdict is Verdict.MATCH


def test_title_alone_never_matches() -> None:
    match = compare(track("Kino", "Blood Type"), track("Viktor Tsoi Tribute", "Blood Type"))

    assert match.verdict is Verdict.NO_MATCH
    assert match.title_score == 1.0


def test_collaboration_credit_matches_one_artist() -> None:
    assert artist_similarity("Burial", "Burial & Four Tet") == 0.9
    assert artist_similarity("Burial & Four Tet", "Four Tet") == 0.9
    assert artist_similarity("The Beatles", "Beatles") == 1.0


def test_similarity_tolerates_word_order_and_typos() -> None:
    assert key_similarity("four tet burial", "burial four tet") == 1.0
    assert key_similarity("radiohead", "radiohed") > 0.85
    assert key_similarity("", "radiohead") == 0.0


def test_non_latin_titles_compare_by_their_own_script() -> None:
    assert title_similarity("Группа крови", "ГРУППА КРОВИ") == 1.0
    assert title_similarity("Группа крови", "Gruppa krovi") < 0.5
    assert title_similarity("風をあつめて", "風をあつめて (Remastered)") == 1.0


MBID = {IdKind.MUSICBRAINZ_ARTIST: "f22942a1"}


@pytest.mark.parametrize(
    ("reference", "candidate", "verdict"),
    [
        (
            NameKey("Aphex Twin", EntityKind.ARTIST),
            NameKey("aphex twin", EntityKind.ARTIST),
            Verdict.MATCH,
        ),
        (
            NameKey("Aphex Twin", EntityKind.ARTIST),
            NameKey("Autechre", EntityKind.ARTIST),
            Verdict.NO_MATCH,
        ),
        (
            NameKey("Aphex Twin", EntityKind.ARTIST),
            NameKey("Aphex Twin & Squarepusher", EntityKind.ARTIST),
            Verdict.MATCH,
        ),
        (NameKey("Warp", EntityKind.LABEL), NameKey("Warp", EntityKind.ARTIST), Verdict.NO_MATCH),
        (NameKey("Warp", EntityKind.LABEL), NameKey("WARP", EntityKind.LABEL), Verdict.MATCH),
        (
            NameKey("Aphex Twin", EntityKind.ARTIST, MBID),
            NameKey("AFX", EntityKind.ARTIST, MBID),
            Verdict.MATCH,
        ),
        (
            NameKey("Aphex Twin", EntityKind.ARTIST, MBID),
            NameKey("Aphex Twin", EntityKind.ARTIST, {IdKind.MUSICBRAINZ_ARTIST: "other"}),
            Verdict.NO_MATCH,
        ),
        (
            NameKey("Aphex Twin", EntityKind.ARTIST, MBID),
            NameKey("Aphex Twin", EntityKind.ARTIST, {IdKind.DISCOGS_ARTIST: "45"}),
            Verdict.MATCH,
        ),
    ],
)
def test_names_match_by_shared_ids_else_by_name(
    reference: NameKey,
    candidate: NameKey,
    verdict: Verdict,
) -> None:
    assert compare_names(reference, candidate).verdict is verdict


def test_name_comparison_is_traced(traced: Callable[[str], list[dict[str, object]]]) -> None:
    compare_names(
        NameKey("Aphex Twin", EntityKind.ARTIST, MBID),
        NameKey("Aphex Twin", EntityKind.ARTIST, {IdKind.MUSICBRAINZ_ARTIST: "other"}),
    )

    [event] = traced("match.compare")
    assert event["failed"] == ["ids"]
    assert event["name_score"] == 1.0
    assert event["reference"] == {"name": "Aphex Twin", "kind": "artist", "ids": MBID}
