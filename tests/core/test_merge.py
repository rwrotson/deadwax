from datetime import UTC, datetime

import pytest

from deadwax.core import (
    QUERY_SOURCE,
    AdapterError,
    CandidateLabel,
    Credit,
    Entity,
    EntityKind,
    EntityType,
    ErrorKind,
    IdKind,
    Link,
    LinkTarget,
    Metric,
    MetricKind,
    Partial,
    Provenance,
    Query,
    Rating,
    RecordCandidate,
    Relation,
    RelationKind,
    Scope,
    Tag,
    TagKind,
    Text,
    TextKind,
    VersionInfo,
    VersionKind,
    merge,
    parse_query,
)

NOW = datetime(2026, 11, 12, tzinfo=UTC)
TRACK = parse_query("Everything but the Girl - Missing", EntityKind.TRACK)


def provenance(source: str) -> list[Provenance]:
    return [Provenance(source=source, url=f"https://{source}.example/missing")]


def candidate(title: str = "Missing", **fields: object) -> RecordCandidate:
    values: dict[str, object] = {"artist": "Everything but the Girl", "title": title}
    return RecordCandidate.model_validate(values | fields)


def partial(source: str, record: RecordCandidate | None, **facts: object) -> Partial:
    return Partial.model_validate({"source": source, "candidate": record} | facts)


def tag(name: str, source: str, weight: float | None = None) -> Tag:
    return Tag(name=name, scope=Scope.RECORDING, weight=weight, sources=provenance(source))


def test_matching_partials_merge_with_provenance() -> None:
    partials = [
        partial(
            "musicbrainz",
            candidate(date="1994", isrcs=["GBAHT9400001"], ids={IdKind.MUSICBRAINZ_RECORDING: "a"}),
            tags=[tag("Pop", "musicbrainz", 0.5)],
        ),
        partial(
            "discogs",
            candidate(date="1994-05-30", isrcs=["gb-aht-94-00001"]),
            tags=[tag("pop", "discogs"), tag("House", "discogs")],
        ),
    ]

    dossier = merge(TRACK, partials, generated_at=NOW)

    assert dossier.found
    assert dossier.identity.artist is not None
    assert dossier.identity.artist.value == "Everything but the Girl"
    assert [s.source for s in dossier.identity.artist.sources] == ["musicbrainz", "discogs"]
    assert dossier.identity.date is not None
    assert dossier.identity.date.value == "1994-05-30"
    assert [isrc.value for isrc in dossier.identity.isrcs] == ["GBAHT9400001"]
    assert dossier.identity.discrepancies == []
    pop = dossier.tags[0]
    assert (pop.name, pop.weight, [s.source for s in pop.sources]) == (
        "Pop",
        0.5,
        ["musicbrainz", "discogs"],
    )
    assert [t.name for t in dossier.tags] == ["Pop", "House"]
    assert dossier.generated_at == NOW


def test_other_version_is_kept_out_and_reported() -> None:
    remix = candidate("Missing (Todd Terry Remix)", date="1995", url="https://x.example/remix")
    partials = [
        partial("musicbrainz", candidate(date="1994")),
        partial("lastfm", remix, tags=[tag("house", "lastfm")]),
    ]

    dossier = merge(TRACK, partials, generated_at=NOW)

    assert dossier.tags == []
    assert dossier.identity.version.kind is VersionKind.ORIGINAL
    assert dossier.identity.date is not None
    assert dossier.identity.date.value == "1994"
    [relation] = dossier.relations
    assert relation.kind is RelationKind.OTHER_VERSION
    assert relation.target.name == "Missing (Todd Terry Remix)"
    assert relation.note == "remix: Todd Terry Remix"
    [discrepancy] = dossier.identity.discrepancies
    assert discrepancy.field == "version"
    assert [v.value for v in discrepancy.values] == ["original", "remix: Todd Terry Remix"]
    assert discrepancy.values[1].sources == [
        Provenance(source="lastfm", url="https://x.example/remix"),
    ]


def test_version_discrepancy_without_matching_title_cites_the_query() -> None:
    dossier = merge(TRACK, [partial("lastfm", candidate("Missing - Live"))], generated_at=NOW)

    assert not dossier.found
    [discrepancy] = dossier.identity.discrepancies
    assert discrepancy.values[0].sources == [Provenance(source=QUERY_SOURCE)]


def test_album_other_version_becomes_release_relation() -> None:
    query = parse_query("Burial - Untrue", EntityKind.ALBUM)
    deluxe = RecordCandidate(
        artist="Burial",
        title="Untrue (Deluxe Edition)",
        kind=EntityKind.ALBUM,
    )

    dossier = merge(query, [partial("discogs", deluxe)], generated_at=NOW)

    [relation] = dossier.relations
    assert (relation.scope, relation.target.type) == (Scope.RELEASE, EntityType.RELEASE)


def test_unrelated_candidate_becomes_no_match_error() -> None:
    other = RecordCandidate(artist="Somebody Else", title="Missing", url="https://x.example/o")

    dossier = merge(
        TRACK,
        [partial("discogs", other, tags=[tag("x", "discogs")])],
        generated_at=NOW,
    )

    assert dossier.tags == []
    [error] = dossier.errors
    assert (error.source, error.kind, error.url) == (
        "discogs",
        ErrorKind.NO_MATCH,
        "https://x.example/o",
    )


def test_disagreements_are_recorded_not_smoothed() -> None:
    partials = [
        partial("musicbrainz", candidate(date="1994", ids={IdKind.DISCOGS_RELEASE: "1"})),
        partial("discogs", candidate(date="1995-01", ids={IdKind.DISCOGS_RELEASE: "2"})),
        partial("bandcamp", candidate(date="1994-06", artist="Everything But The Girl")),
    ]

    dossier = merge(TRACK, partials, generated_at=NOW)

    fields = {d.field: [v.value for v in d.values] for d in dossier.identity.discrepancies}
    assert fields == {"date": ["1994-06", "1995-01"], "ids.discogs_release": ["1", "2"]}
    assert dossier.identity.date is not None
    assert dossier.identity.date.value == "1994-06"
    assert [i.value for i in dossier.identity.external_ids] == ["1", "2"]


def test_artist_spelling_conflict_is_a_discrepancy() -> None:
    query = parse_query("Kino - Gruppa krovi", EntityKind.TRACK)
    partials = [
        partial("a", RecordCandidate(artist="Kino", title="Gruppa krovi")),
        partial("b", RecordCandidate(artist="Kino", title="Gruppa krovi")),
        partial("c", RecordCandidate(artist="Kinoo", title="Gruppa krovi")),
    ]

    dossier = merge(query, partials, generated_at=NOW)

    assert dossier.identity.artist is not None
    assert dossier.identity.artist.value == "Kino"
    [discrepancy] = dossier.identity.discrepancies
    assert discrepancy.field == "artist"


def test_url_query_uses_first_candidate_as_reference() -> None:
    query = parse_query("https://everythingbutthegirl.bandcamp.com/track/missing")
    partials = [
        partial("bandcamp", candidate(kind=EntityKind.TRACK)),
        partial("musicbrainz", candidate("Missing (Live)")),
        partial("discogs", candidate()),
    ]

    dossier = merge(query, partials, generated_at=NOW)

    assert dossier.identity.kind is EntityKind.TRACK
    assert dossier.identity.title is not None
    assert [s.source for s in dossier.identity.title.sources] == ["bandcamp", "discogs"]
    assert [r.kind for r in dossier.relations] == [RelationKind.OTHER_VERSION]


def test_url_query_without_candidates_keeps_facts() -> None:
    query = Query(url="https://example.com/x")

    dossier = merge(query, [partial("odesli", None, links=[])], generated_at=NOW)

    assert not dossier.found
    assert dossier.identity.kind is None


def test_explicit_version_is_used_for_identity() -> None:
    query = parse_query("Radiohead - Paranoid Android", EntityKind.TRACK)
    live = VersionInfo(kind=VersionKind.LIVE, detail="Glastonbury 1997")
    partials = [
        partial("a", RecordCandidate(artist="Radiohead", title="Paranoid Android")),
        partial("b", RecordCandidate(artist="Radiohead", title="Paranoid Android", version=live)),
    ]

    dossier = merge(query, partials, generated_at=NOW)

    assert dossier.identity.version.kind is VersionKind.ORIGINAL
    assert dossier.relations[0].note == "live: Glastonbury 1997"


def test_labels_codes_and_kind_are_combined() -> None:
    query = Query(url="https://example.com/untrue")
    partials = [
        partial(
            "discogs",
            RecordCandidate(
                artist="Burial",
                title="Untrue",
                kind=EntityKind.ALBUM,
                labels=[CandidateLabel(name="Hyperdub", catalog_number="HDBCD002")],
                upcs=["5055300315829"],
                copyrights=["℗ 2007 Hyperdub"],
            ),
        ),
        partial(
            "musicbrainz",
            RecordCandidate(
                artist="Burial",
                title="Untrue",
                labels=[
                    CandidateLabel(name="hyperdub", catalog_number="hdbcd 002"),
                    CandidateLabel(name="Hyperdub", catalog_number="HDBLP002"),
                ],
                upcs=["05055300315829"],
                copyrights=["(P) 2007 Hyperdub", "© 2007 Hyperdub"],
            ),
        ),
    ]

    dossier = merge(query, partials, generated_at=NOW)

    assert dossier.identity.kind is EntityKind.ALBUM
    assert [(label.catalog_number, len(label.sources)) for label in dossier.identity.labels] == [
        ("HDBCD002", 2),
        ("HDBLP002", 1),
    ]
    [upc] = dossier.identity.upcs
    assert (upc.value, len(upc.sources)) == ("5055300315829", 2)
    assert [(line.value, len(line.sources)) for line in dossier.identity.copyrights] == [
        ("℗ 2007 Hyperdub", 2),
        ("© 2007 Hyperdub", 1),
    ]


def test_facts_are_deduplicated_and_ordered_by_scope() -> None:
    query = parse_query("Burial - Untrue", EntityKind.ALBUM)
    record = RecordCandidate(artist="Burial", title="Untrue")
    target = Entity(type=EntityType.ARTIST, name="Kode9")
    facts_a = {
        "credits": [
            Credit(role="Producer", name="Burial", scope=Scope.RECORDING, sources=provenance("a")),
            Credit(
                role="Mastered By",
                name="Stuart Hawkes",
                scope=Scope.RELEASE,
                sources=provenance("a"),
            ),
        ],
        "texts": [
            Text(kind=TextKind.USER, body="Great.", scope=Scope.RELEASE, sources=provenance("a")),
            Text(kind=TextKind.REVIEW, body="Rain.", scope=Scope.RELEASE, sources=provenance("a")),
            Text(kind=TextKind.WIKI, body="Bio.", scope=Scope.ARTIST, sources=provenance("a")),
        ],
        "relations": [
            Relation(
                kind=RelationKind.SIMILAR,
                target=target,
                scope=Scope.ARTIST,
                sources=provenance("a"),
            ),
            Relation(
                kind=RelationKind.LABEL,
                target=target,
                scope=Scope.RELEASE,
                sources=provenance("a"),
            ),
        ],
        "links": [
            Link(
                service="spotify",
                url="https://open.spotify.com/track/1",
                target=LinkTarget.TRACK,
                sources=provenance("a"),
            ),
            Link(
                service="spotify",
                url="https://open.spotify.com/album/1/",
                target=LinkTarget.ALBUM,
                sources=provenance("a"),
            ),
        ],
        "tags": [
            Tag(name="dubstep", kind=TagKind.GENRE, scope=Scope.ARTIST, sources=provenance("a")),
            Tag(name="2-step", kind=TagKind.STYLE, scope=Scope.RELEASE, sources=provenance("a")),
        ],
    }
    facts_b = {
        "credits": [
            Credit(role="producer", name="burial", scope=Scope.RECORDING, sources=provenance("b")),
        ],
        "links": [
            Link(
                service="spotify",
                url="https://www.open.spotify.com/album/1",
                target=LinkTarget.ALBUM,
                sources=provenance("b"),
            ),
        ],
        "tags": [Tag(name="2 Step", scope=Scope.RELEASE, weight=0.2, sources=provenance("b"))],
    }

    dossier = merge(
        query,
        [partial("a", record, **facts_a), partial("b", record, **facts_b)],
        generated_at=NOW,
    )

    assert [c.role for c in dossier.credits] == ["Mastered By", "Producer"]
    assert len(dossier.credits[1].sources) == 2
    assert [t.kind for t in dossier.texts] == [TextKind.REVIEW, TextKind.USER, TextKind.WIKI]
    assert [r.kind for r in dossier.relations] == [RelationKind.LABEL, RelationKind.SIMILAR]
    assert [link.target for link in dossier.links] == [LinkTarget.ALBUM, LinkTarget.TRACK]
    assert len(dossier.links[0].sources) == 2
    assert [(t.name, t.weight) for t in dossier.tags] == [("2-step", 0.2), ("dubstep", None)]


def test_adapter_errors_are_passed_through() -> None:
    failure = AdapterError(source="discogs", kind=ErrorKind.TIMEOUT, reason="no answer in 10 s")
    blocked = AdapterError(source="bandcamp", kind=ErrorKind.BLOCKED, reason="challenge page")

    dossier = merge(
        TRACK,
        [partial("bandcamp", None, errors=[blocked])],
        [failure],
        generated_at=NOW,
    )

    assert dossier.errors == [failure, blocked]


@pytest.mark.parametrize("kind", [EntityKind.TRACK, EntityKind.ALBUM])
def test_empty_merge(kind: EntityKind) -> None:
    query = parse_query("A - B", kind)

    dossier = merge(query, [], generated_at=NOW)

    assert not dossier.found
    assert dossier.identity.kind is kind


def test_scores_without_body_are_kept_apart_by_publication_and_rating() -> None:
    def score(publication: str, value: float, source: str = "wikipedia") -> Text:
        return Text(
            kind=TextKind.REVIEW,
            body="",
            publication=publication,
            rating=Rating(value=value, scale=5),
            scope=Scope.RECORDING,
            sources=provenance(source),
        )

    texts = [score("AllMusic", 4.5), score("Q", 5), score("AllMusic", 4)]
    other = [score("allmusic", 4.5, "lastfm")]

    dossier = merge(
        TRACK,
        [
            partial("wikipedia", candidate(), texts=texts),
            partial("lastfm", candidate(), texts=other),
        ],
        generated_at=NOW,
    )

    assert [(t.publication, t.rating.value if t.rating else None) for t in dossier.texts] == [
        ("AllMusic", 4.5),
        ("Q", 5),
        ("AllMusic", 4),
    ]
    assert [p.source for p in dossier.texts[0].sources] == ["wikipedia", "lastfm"]


def cover(artist: str | None, source: str, **target: object) -> Relation:
    return Relation(
        kind=RelationKind.COVERED_BY,
        target=Entity.model_validate(
            {"type": "recording", "name": "Missing", "artist": artist} | target,
        ),
        scope=Scope.WORK,
        sources=provenance(source),
    )


def test_relations_of_one_target_merge_and_fill_the_target() -> None:
    partials = [
        partial(
            "musicbrainz",
            candidate(),
            relations=[cover("Todd Terry", "musicbrainz", ids={IdKind.MUSICBRAINZ_RECORDING: "r"})],
        ),
        partial(
            "secondhandsongs",
            None,
            relations=[
                cover("todd terry", "secondhandsongs", date="1995", url="https://shs.example/1"),
                cover("Someone Else", "secondhandsongs"),
            ],
        ),
    ]

    relations = merge(TRACK, partials, generated_at=NOW).relations

    assert len(relations) == 2
    merged = relations[0]
    assert [p.source for p in merged.sources] == ["musicbrainz", "secondhandsongs"]
    assert merged.target.artist == "Todd Terry"
    assert (merged.target.date, merged.target.url) == ("1995", "https://shs.example/1")
    assert merged.target.ids == {IdKind.MUSICBRAINZ_RECORDING: "r"}


def test_broadcasts_on_other_dates_stay_apart() -> None:
    def broadcast(date: str, source: str) -> Relation:
        return Relation(
            kind=RelationKind.BROADCAST,
            target=Entity(type=EntityType.BROADCAST, name="KEXP: Variety Mix", date=date),
            scope=Scope.RECORDING,
            sources=provenance(source),
        )

    relations = merge(
        TRACK,
        [
            partial("kexp", None, relations=[broadcast("2026-09-15", "kexp")]),
            partial("other", None, relations=[broadcast("2026-09-15", "other")]),
            partial("kexp2", None, relations=[broadcast("2025-01-02", "kexp2")]),
        ],
        generated_at=NOW,
    ).relations

    assert [(r.target.date, len(r.sources)) for r in relations] == [
        ("2026-09-15", 2),
        ("2025-01-02", 1),
    ]


def test_metrics_stay_per_source() -> None:
    def metric(source: str, value: float, scope: Scope = Scope.RECORDING) -> Metric:
        return Metric(kind=MetricKind.LISTENS, value=value, scope=scope, sources=provenance(source))

    metrics = merge(
        TRACK,
        [
            partial("listenbrainz", candidate(), metrics=[metric("listenbrainz", 10)]),
            partial(
                "lastfm",
                candidate(),
                metrics=[metric("lastfm", 99, Scope.ARTIST), metric("lastfm", 20)],
            ),
            partial("other", candidate(title="Missing (Live)"), metrics=[metric("other", 5)]),
        ],
        generated_at=NOW,
    ).metrics

    assert [(m.sources[0].source, m.value, m.scope) for m in metrics] == [
        ("listenbrainz", 10, Scope.RECORDING),
        ("lastfm", 20, Scope.RECORDING),
        ("lastfm", 99, Scope.ARTIST),
    ]
