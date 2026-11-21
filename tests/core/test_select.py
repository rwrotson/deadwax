from datetime import UTC, datetime

from deadwax.core import (
    Capability,
    Credit,
    Dossier,
    Entity,
    EntityKind,
    EntityType,
    Link,
    LinkTarget,
    Metric,
    MetricKind,
    Provenance,
    RecordIdentity,
    Relation,
    RelationKind,
    RelationLimit,
    Request,
    ReviewLink,
    Scope,
    Sourced,
    Tag,
    Text,
    TextKind,
    text_query,
    trim,
)

TRACK = text_query("Radiohead - Reckoner", EntityKind.TRACK)


def by(*sources: str) -> list[Provenance]:
    return [Provenance(source=source) for source in sources]


def tag(name: str, *sources: str) -> Tag:
    return Tag(name=name, scope=Scope.RECORDING, sources=by(*sources))


def relation(kind: RelationKind, target: EntityType, name: str, *sources: str) -> Relation:
    return Relation(
        kind=kind,
        target=Entity(type=target, name=name),
        scope=Scope.RECORDING,
        sources=by(*sources),
    )


def link(url: str, preview: str | None = None) -> Link:
    return Link(
        service="itunes",
        url=url,
        target=LinkTarget.TRACK,
        preview_url=preview,
        sources=by("itunes"),
    )


DOSSIER = Dossier(
    query=TRACK,
    identity=RecordIdentity(title=Sourced(value="Reckoner", sources=by("musicbrainz"))),
    generated_at=datetime(2026, 11, 20, tzinfo=UTC),
    tags=[tag("a", "lastfm"), tag("b", "lastfm", "musicbrainz"), tag("c", "musicbrainz"),
          tag("d", "lastfm")],
    credits=[Credit(role="producer", name="Nigel Godrich", scope=Scope.RECORDING,
                    sources=by("musicbrainz"))],
    texts=[Text(kind=TextKind.WIKI, body="About.", scope=Scope.RECORDING, sources=by("wikipedia"))],
    review_links=[ReviewLink(url="https://example.com/review", sources=by("musicbrainz"))],
    metrics=[Metric(kind=MetricKind.LISTENS, value=10, scope=Scope.RECORDING,
                    sources=by("listenbrainz"))],
    relations=[
        relation(RelationKind.SIMILAR, EntityType.RECORDING, "r1", "lastfm"),
        relation(RelationKind.SIMILAR, EntityType.RECORDING, "r2", "lastfm"),
        relation(RelationKind.SIMILAR, EntityType.RECORDING, "r3", "listenbrainz"),
        relation(RelationKind.SIMILAR, EntityType.ARTIST, "a1", "lastfm"),
        relation(RelationKind.SIMILAR, EntityType.ARTIST, "a2", "lastfm"),
        relation(RelationKind.MEMBER, EntityType.ARTIST, "m1", "musicbrainz"),
    ],
    links=[link("https://music.apple.com/1", "https://audio/1"), link("https://music.apple.com/2")],
)  # fmt: skip


def test_request_for_everything_keeps_the_dossier() -> None:
    assert trim(DOSSIER, Request(query=TRACK)) == DOSSIER


def test_facets_not_requested_are_emptied() -> None:
    dossier = trim(DOSSIER, Request(query=TRACK, facets=frozenset({Capability.CREDITS})))

    assert dossier.credits == DOSSIER.credits
    assert dossier.identity == DOSSIER.identity
    assert (dossier.tags, dossier.texts, dossier.review_links) == ([], [], [])
    assert (dossier.relations, dossier.metrics, dossier.links) == ([], [], [])


def test_previews_without_links_keep_links_with_a_preview() -> None:
    dossier = trim(DOSSIER, Request(query=TRACK, facets=frozenset({Capability.PREVIEWS})))

    assert [item.url for item in dossier.links] == ["https://music.apple.com/1"]


def test_tags_are_capped_per_first_source() -> None:
    dossier = trim(DOSSIER, Request(query=TRACK, tags_per_source=1))

    assert [item.name for item in dossier.tags] == ["a", "c"]


def test_relations_are_filtered_by_kind_and_capped_per_source_and_target() -> None:
    limits = (
        RelationLimit(kind=RelationKind.SIMILAR, target=EntityType.RECORDING, per_source=1),
        RelationLimit(kind=RelationKind.SIMILAR, target=EntityType.ARTIST, per_source=2),
    )

    dossier = trim(DOSSIER, Request(query=TRACK, relations=limits))

    assert [item.target.name for item in dossier.relations] == ["r1", "r3", "a1", "a2"]


def test_empty_relation_limits_drop_every_relation() -> None:
    assert trim(DOSSIER, Request(query=TRACK, relations=())).relations == []


def test_facts_without_sources_share_one_cap() -> None:
    unsourced = DOSSIER.model_copy(update={"tags": [tag("x"), tag("y")]})

    assert [
        item.name for item in trim(unsourced, Request(query=TRACK, tags_per_source=1)).tags
    ] == [
        "x",
    ]
