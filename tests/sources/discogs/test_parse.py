from collections.abc import Callable

import pytest

from deadwax.core import EntityKind, IdKind, RecordKey, RelationKind, Scope, TagKind, TextKind
from deadwax.sources.discogs import models
from deadwax.sources.discogs import parse as p

Recorded = Callable[[str, str], bytes]
API = "https://api.discogs.com"


@pytest.fixture
def ok_computer(recorded: Recorded) -> models.Release:
    body = recorded("paranoid_android", f"GET {API}/releases/4950798")
    return models.Release.model_validate_json(body)


@pytest.fixture
def huerco(recorded: Recorded) -> tuple[models.Master, models.Release]:
    master = models.Master.model_validate_json(recorded("huerco_s", f"GET {API}/masters/1016511"))
    release = models.Release.model_validate_json(
        recorded("huerco_s", f"GET {API}/releases/8541536")
    )
    return master, release


def test_album_candidate(huerco: tuple[models.Master, models.Release]) -> None:
    master, release = huerco

    candidate = p.album_candidate(release, master)

    assert (candidate.artist, candidate.date, candidate.url) == (
        "Huerco S.",
        "2016-06-20",
        "https://www.discogs.com/master/1016511",
    )
    assert [(label.name, label.catalog_number) for label in candidate.labels] == [
        ("Proibito", "PRB018")
    ]
    assert candidate.ids == {
        IdKind.DISCOGS_RELEASE: "8541536",
        IdKind.DISCOGS_MASTER: "1016511",
        IdKind.DISCOGS_ARTIST: "2367552",
    }


def test_release_without_master(ok_computer: models.Release) -> None:
    candidate = p.album_candidate(ok_computer, None)

    assert candidate.url == "https://www.discogs.com/release/4950798"
    assert candidate.upcs == ["724385522918"]
    assert candidate.ids[IdKind.DISCOGS_MASTER] == "21491"


def test_track_credits_cover_release_wide_and_track_credits(ok_computer: models.Release) -> None:
    track = p.find_track(ok_computer, RecordKey("Radiohead", "Paranoid Android", EntityKind.TRACK))

    assert track is not None
    people = p.release_credits(ok_computer, track)
    candidate = p.track_candidate(ok_computer, None, track)

    assert ("mixed", "Nigel Godrich") in {(c.role, c.name) for c in people}
    assert {c.scope for c in people} <= {Scope.RELEASE, Scope.RECORDING}
    assert (candidate.kind, candidate.title) == (EntityKind.TRACK, "Paranoid Android")
    assert p.find_track(ok_computer, RecordKey("Radiohead", "Creep", EntityKind.TRACK)) is None


def test_album_credits_name_their_tracks() -> None:
    release = models.Release(
        id=1,
        title="R",
        extraartists=[models.ArtistCredit(name="A (2)", role="Mixed By", tracks="A1 to A2")],
        tracklist=[
            models.Track(position="A1", title="One"),
            models.Track(
                position="A2",
                title="Two",
                extraartists=[models.ArtistCredit(name="B", anv="Bee", role="Vocals [Lead]")],
            ),
        ],
    )

    people = p.release_credits(release)
    for_two = p.release_credits(release, release.tracklist[1])

    assert [(c.role, c.name, c.detail, c.scope) for c in people] == [
        ("mixed", "A", "tracks A1 to A2", Scope.RELEASE),
        ("vocals", "Bee", "Lead, track A2", Scope.RECORDING),
    ]
    assert [(c.role, c.name, c.scope) for c in for_two] == [
        ("mixed", "A", Scope.RECORDING),
        ("vocals", "Bee", Scope.RECORDING),
    ]


def test_roles_and_track_ranges() -> None:
    assert p.roles("Producer, Arranged By [Strings, Brass], Written-By") == [
        ("producer", None),
        ("arranged", "Strings, Brass"),
        ("written", None),
    ]
    assert p.roles("") == []
    positions = ["A1", "A2", "B1", "B2"]
    assert p.covers("A1, B1", "B1", positions)
    assert p.covers("A2 to B2", "B1", positions)
    assert not p.covers("A1 to A2", "B1", positions)
    assert not p.covers("C1 to C2", "C1", positions)


def test_names() -> None:
    artists = [
        models.ArtistCredit(name="Deadbeat (3)", join="&"),
        models.ArtistCredit(name="Camara", join=","),
        models.ArtistCredit(name="X", anv="Ex"),
    ]

    assert p.credit_name(artists) == "Deadbeat & Camara, Ex"
    assert p.clean_name("Pendant (2)") == "Pendant"
    assert p.split_title("Various - Club Mix") == ("Various", "Club Mix")
    assert p.split_title("No separator") == ("", "No separator")


def test_tags_and_notes(huerco: tuple[models.Master, models.Release]) -> None:
    master, release = huerco

    tags = p.tags(master.genres, master.styles, Scope.RELEASE_GROUP, None)
    notes = p.notes(release.notes, "Release notes", Scope.RELEASE, "https://d")

    assert [(t.name, t.kind) for t in tags] == [
        ("Electronic", TagKind.GENRE),
        ("Ambient", TagKind.STYLE),
        ("Experimental", TagKind.STYLE),
    ]
    assert notes[0].kind is TextKind.WIKI
    assert notes[0].body.startswith("Recorded between 2014")
    assert p.notes("  ", "x", Scope.RELEASE, "https://d") == []


def test_placeholder_labels_and_dates() -> None:
    release = models.Release(
        id=1,
        title="R",
        released="1988-00-00",
        labels=[
            models.LabelCredit(id=1818, name="Not On Label", catno="none"),
            models.LabelCredit(id=5, name="Real (2)", catno="none"),
            models.LabelCredit(id=5, name="Real (2)", catno="R1"),
            models.LabelCredit(name="No Id", catno=""),
        ],
    )

    assert [(label.name, label.catalog_number) for label in p.labels(release)] == [
        ("Real", None),
        ("Real", "R1"),
        ("No Id", None),
    ]
    assert [r.target.name for r in p.label_relations(release)] == ["Real", "No Id"]
    assert p.album_candidate(release, None).date == "1988"
    assert p.album_candidate(models.Release(id=2, title="R", year=1990), None).date == "1990"
    assert p.album_candidate(models.Release(id=3, title="R", released="0"), None).date is None


def test_versions_and_label_releases(recorded: Recorded) -> None:
    versions = models.Versions.model_validate_json(
        recorded("paranoid_android", f"GET {API}/masters/21491/versions?per_page=25")
    )
    catalog = models.LabelReleases(
        releases=[
            models.LabelRelease(id=1, title="OK Computer", artist="Radiohead"),
            models.LabelRelease(id=2, title="Other", artist="A (2)", catno="C1", year=2000),
            models.LabelRelease(id=3, title="Other", artist="A"),
            *(models.LabelRelease(id=10 + n, title=f"T{n}") for n in range(20)),
        ]
    )

    others = p.version_relations(versions.versions, 4950798)
    releases = p.label_release_relations(catalog.releases, "Parlophone", 2294, "OK Computer")

    assert 0 < len(others) <= p.VERSIONS_LIMIT
    assert "4950798" not in {r.target.ids[IdKind.DISCOGS_RELEASE] for r in others}
    assert releases[0].target.name == "Other"
    assert releases[0].note == "Parlophone, C1"
    assert len(releases) == p.LABEL_RELEASES_LIMIT


def test_artist_relations(recorded: Recorded) -> None:
    radiohead = models.Artist.model_validate_json(
        recorded("paranoid_android", f"GET {API}/artists/3840")
    )
    person = models.Artist(
        id=1,
        name="P",
        groups=[models.ArtistRef(id=2, name="G")],
        aliases=[models.ArtistRef(id=3, name="Unknown (21)"), models.ArtistRef(id=4, name="Alias")],
        members=[models.ArtistRef(id=5, name="Old", active=False)],
    )

    relations = p.artist_relations(person)

    assert "Thom Yorke" in {r.target.name for r in p.artist_relations(radiohead)}
    assert [(r.kind, r.target.name, r.note) for r in relations] == [
        (RelationKind.MEMBER, "Old", "former"),
        (RelationKind.PROJECT, "G", None),
        (RelationKind.PROJECT, "Alias", "alias"),
    ]


def test_compilations() -> None:
    results = [
        models.SearchResult(id=1, type="release", title="Various - Hits", master_id=100,
                            label=["L"], catno="C"),
        models.SearchResult(id=2, type="release", title="Various - Hits", master_id=100),
        models.SearchResult(id=3, type="release", title="Band - Own", master_id=7),
        models.SearchResult(id=4, type="release", title="Band - Own Release"),
        *(models.SearchResult(id=10 + n, type="release", title=f"V - C{n}") for n in range(20)),
    ]  # fmt: skip

    relations = p.compilation_relations(results, {7, 4})

    assert relations[0].target.name == "Hits"
    assert relations[0].note == "L, C"
    assert [r.target.ids[IdKind.DISCOGS_RELEASE] for r in relations[:2]] == ["1", "10"]
    assert len(relations) == p.COMPILATIONS_LIMIT


def test_search_results() -> None:
    results = [
        models.SearchResult(id=1, type="master", title="Radiohead - Kid A"),
        models.SearchResult(id=2, type="master", title="Radiohead - OK Computer"),
    ]

    album = p.pick_result(RecordKey("Radiohead", "OK Computer", EntityKind.ALBUM), results)
    track = p.pick_result(RecordKey("Radiohead", "Airbag", EntityKind.TRACK), results)
    nobody = p.pick_result(RecordKey("Blur", "Song 2", EntityKind.TRACK), results)

    assert album is not None
    assert album.id == 2
    assert track is not None
    assert track.id == 1
    assert nobody is None


def test_links_and_appearance(huerco: tuple[models.Master, models.Release]) -> None:
    master, release = huerco

    links = p.links(release, master)
    on_master = p.appears_on(release, master)
    on_release = p.appears_on(release, None)

    assert [link.url for link in links] == [
        "https://www.discogs.com/master/1016511",
        "https://www.discogs.com/release/8541536",
        "https://www.discogs.com/artist/2367552",
    ]
    assert on_master.target.ids[IdKind.DISCOGS_MASTER] == "1016511"
    assert IdKind.DISCOGS_MASTER not in on_release.target.ids


def test_reviews_from_json_ld() -> None:
    page = b"""
    <script type="application/ld+json">{"@type": "MusicRelease", "review": [
      {"reviewBody": " Great ", "author": {"name": "fan"}, "datePublished": "2020-01-02T10:00",
       "reviewRating": {"ratingValue": "4", "bestRating": 5}},
      {"reviewBody": "Fine", "author": "plain", "reviewRating": {"ratingValue": "n/a"}},
      {"description": ""}, "junk"]}</script>
    <script type="application/ld+json">{"@type": "Product", "review": {"reviewBody": "One",
      "reviewRating": {"ratingValue": 3}}}</script>
    """

    reviews = p.reviews(page, "https://www.discogs.com/release/1")

    assert [(r.body, r.author, r.date) for r in reviews] == [
        ("Great", "fan", "2020-01-02"),
        ("Fine", "plain", None),
        ("One", None, None),
    ]
    assert reviews[0].rating is not None
    assert (reviews[0].rating.value, reviews[0].rating.scale) == (4.0, 5.0)
    assert reviews[1].rating is None
    assert reviews[2].rating is not None
    assert reviews[2].rating.scale == 5.0
    assert p.reviews(b"<html></html>", "https://www.discogs.com/release/1") == []
