import pytest

from deadwax.core import (
    EntityKind,
    LinkTarget,
    RecordKey,
    RelationKind,
    Scope,
    VersionInfo,
    VersionKind,
)
from deadwax.sources.musicbrainz import models
from deadwax.sources.musicbrainz import parse as p

ARTIST = {"id": "a1", "name": "Everything but the Girl"}
CREDIT = [{"name": "Everything but the Girl", "joinphrase": "", "artist": ARTIST}]


def recording(rid: str, **fields: object) -> models.Recording:
    return models.Recording.model_validate(
        {"id": rid, "title": "Missing", "artist-credit": CREDIT} | fields
    )


def relation(**fields: object) -> models.Relation:
    return models.Relation.model_validate(fields)


@pytest.mark.parametrize(
    ("title", "comment", "expected"),
    [
        ("Missing", "", VersionKind.ORIGINAL),
        ("Missing", "“Amplified Heart” album original mix", VersionKind.ORIGINAL),
        ("Missing", "live, 1997: London, England", VersionKind.LIVE),
        ("Missing", "Todd Terry remix", VersionKind.REMIX),
        ("Missing", "single version", VersionKind.EDIT),
        ("Missing", "explicit", VersionKind.EDIT),
        ("Missing", "deluxe", VersionKind.ORIGINAL),
        ("Missing (Todd Terry remix)", "", VersionKind.REMIX),
        ("Missing (Todd Terry remix)", "live", VersionKind.REMIX),
    ],
)
def test_recording_version(title: str, comment: str, expected: VersionKind) -> None:
    assert p.recording_version(title, comment).kind is expected


@pytest.mark.parametrize(
    ("comment", "excerpt"),
    [
        ("part of “Grandmix: The 90s Edition” DJ-mix", True),
        ("part of a “Pacha Classics” (AU) DJ\u2010mix", True),
        ("DJ mix version", True),
        ("live, 1996", False),
        ("", False),
    ],
)
def test_mix_excerpts(comment: str, excerpt: bool) -> None:
    assert p.is_mix_excerpt(comment) is excerpt


def test_ranking_prefers_official_main_releases_then_year_then_release_count() -> None:
    album = {"id": "rg1", "primary-type": "Album"}
    compilation = {"id": "rg2", "primary-type": "Album", "secondary-types": ["Compilation"]}
    official = {"status": "Official"}
    candidates = [
        recording(
            "partial-date",
            **{
                "first-release-date": "1994-06",
                "releases": [official | {"id": "1", "release-group": compilation}],
            },
        ),
        recording(
            "few",
            **{
                "first-release-date": "1994-06-13",
                "releases": [official | {"id": "2", "release-group": album}],
            },
        ),
        recording(
            "many",
            **{
                "first-release-date": "1994-06-13",
                "releases": [official | {"id": str(i), "release-group": album} for i in range(3)],
            },
        ),
        recording("excerpt", disambiguation="part of “x” DJ-mix"),
        recording("video", video=True),
        recording("other", title="Walking Wounded"),
    ]

    ranked = p.rank_recordings(
        RecordKey("Everything but the Girl", "Missing", EntityKind.TRACK), candidates
    )

    assert [r.id for r in ranked] == ["many", "few", "partial-date"]


def test_first_release_prefers_official_main_releases() -> None:
    releases = [
        models.ReleaseRef.model_validate({"id": "bootleg", "status": "Bootleg", "date": "1990"}),
        models.ReleaseRef.model_validate(
            {
                "id": "comp",
                "status": "Official",
                "date": "1993",
                "release-group": {
                    "id": "g",
                    "secondary-types": ["Compilation"],
                    "primary-type": "Album",
                },
            }
        ),
        models.ReleaseRef.model_validate(
            {
                "id": "album",
                "status": "Official",
                "date": "1994",
                "release-group": {"id": "h", "primary-type": "Album"},
            }
        ),
    ]

    first = p.first_release(releases)

    assert first is not None
    assert first.id == "album"
    assert p.first_release([]) is None


@pytest.mark.parametrize(
    ("kind", "direction", "expected", "note"),
    [
        ("remix", "forward", RelationKind.REMIX_OF, None),
        ("remix", "backward", RelationKind.REMIXED_BY, None),
        ("samples material", "forward", RelationKind.SAMPLES, None),
        ("samples material", "backward", RelationKind.SAMPLED_BY, None),
        ("mashes up", "backward", RelationKind.SAMPLED_BY, "mash-up"),
        ("edit", "forward", RelationKind.OTHER_VERSION, "edit"),
    ],
)
def test_recording_relation_directions(
    kind: str, direction: str, expected: RelationKind, note: str | None
) -> None:
    target = {"id": "r9", "title": "Other", "artist-credit": CREDIT}
    found = p.recording_relations(
        [
            relation(
                type=kind, direction=direction, **{"target-type": "recording"}, recording=target
            ),
            relation(
                type="music video",
                direction="forward",
                **{"target-type": "recording"},
                recording=target,
            ),
            relation(
                type=kind,
                direction=direction,
                **{"target-type": "recording"},
                recording=target | {"video": True},
            ),
        ],
        Scope.RECORDING,
        "https://musicbrainz.org/recording/r1",
    )

    assert [(r.kind, r.note, r.target.artist) for r in found] == [
        (expected, note, "Everything but the Girl")
    ]


WORK = models.Work.model_validate(
    {
        "id": "w1",
        "title": "Missing",
        "relations": [
            {
                "type": "performance",
                "target-type": "recording",
                "attributes": ["cover"],
                "recording": {"id": "c1", "title": "Missing"},
            },
            {
                "type": "performance",
                "target-type": "recording",
                "attributes": [],
                "recording": {"id": "o1", "title": "Missing"},
            },
            {
                "type": "performance",
                "target-type": "recording",
                "attributes": ["cover"],
                "recording": {"id": "r1", "title": "Missing"},
            },
        ],
    }
)


@pytest.mark.parametrize(
    ("version", "is_cover", "expected"),
    [
        (VersionKind.ORIGINAL, False, [(RelationKind.COVERED_BY, "c1")]),
        (VersionKind.ORIGINAL, True, [(RelationKind.COVER_OF, "w1")]),
        (VersionKind.REMIX, False, [(RelationKind.REMIX_OF, "w1")]),
        (VersionKind.LIVE, False, [(RelationKind.OTHER_VERSION, "w1")]),
    ],
)
def test_work_relations(
    version: VersionKind, is_cover: bool, expected: list[tuple[RelationKind, str]]
) -> None:
    found = p.work_relations(WORK, "r1", VersionInfo(kind=version), is_cover)

    assert [(r.kind, next(iter(r.target.ids.values()))) for r in found] == expected


def test_tags_are_weighted_and_genres_marked() -> None:
    tags = p.tags(
        [
            models.Tag(name="90s", count=2),
            models.Tag(name="house", count=4),
            models.Tag(name="bad", count=-1),
        ],
        [models.Tag(name="house", count=4)],
        Scope.RECORDING,
        "https://musicbrainz.org/recording/r1",
    )

    assert [(t.name, t.kind.value, t.weight) for t in tags] == [
        ("house", "genre", 1.0),
        ("90s", "tag", 0.5),
    ]
    assert p.tags([], [], Scope.RECORDING, "u") == []


def test_url_relations_give_ids_and_links() -> None:
    relations = [
        relation(
            type="wikidata",
            **{"target-type": "url"},
            url={"resource": "https://www.wikidata.org/wiki/Q3859219"},
        ),
        relation(
            type="discogs",
            **{"target-type": "url"},
            url={"resource": "https://www.discogs.com/master/21491"},
        ),
        relation(
            type="free streaming",
            **{"target-type": "url"},
            url={"resource": "https://open.spotify.com/album/1"},
        ),
        relation(
            type="other databases",
            **{"target-type": "url"},
            url={"resource": "https://rateyourmusic.com/x"},
        ),
        relation(type="producer", **{"target-type": "artist"}, artist=ARTIST),
    ]

    assert p.url_ids(relations) == {"wikidata": "Q3859219", "discogs_master": "21491"}
    assert [(link.service, link.target) for link in p.links(relations, LinkTarget.TRACK, "u")] == [
        ("spotify", LinkTarget.ALBUM)
    ]


def test_phrase_escapes_quotes() -> None:
    assert p.phrase('Say "Hi" \\ bye') == '"Say \\"Hi\\" \\\\ bye"'
