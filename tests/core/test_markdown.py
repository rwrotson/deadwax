from datetime import UTC, datetime

from deadwax.core import (
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
    Text,
    TextKind,
    merge,
    parse_query,
    to_markdown,
)

NOW = datetime(2026, 11, 12, tzinfo=UTC)
SOURCE = [Provenance(source="bandcamp", url="https://burial.bandcamp.com/album/untrue")]


def untrue_dossier() -> str:
    query = parse_query("Burial - Untrue (Deluxe)", EntityKind.ALBUM)
    record = RecordCandidate(
        artist="Burial",
        title="Untrue (Deluxe)",
        date="2007-11-05",
        labels=[CandidateLabel(name="Hyperdub", catalog_number="HDBCD002")],
        isrcs=["GBAAA0700001"],
        upcs=["5055300315829"],
        ids={IdKind.DISCOGS_MASTER: "89497"},
        url=SOURCE[0].url,
    )
    other = RecordCandidate(artist="Burial", title="Untrue (Deluxe)", date="2008")
    texts = [
        Text(
            kind=TextKind.REVIEW,
            body="Rain on glass.\n\nSecond paragraph.",
            publication="Pitchfork",
            author="Critic",
            rating=Rating(value=9.0, scale=10),
            scope=Scope.RELEASE,
            sources=SOURCE,
        ),
        Text(
            kind=TextKind.SHOP,
            body="Shop copy.",
            rating=Rating(text="A-"),
            scope=Scope.RELEASE,
            sources=[Provenance(source="shop")],
        ),
        Text(
            kind=TextKind.USER,
            body="Fan note.",
            rating=Rating(value=5),
            scope=Scope.RELEASE,
            sources=SOURCE,
        ),
        Text(kind=TextKind.LABEL, body="Label copy.", scope=Scope.RELEASE, sources=SOURCE),
        Text(
            kind=TextKind.REVIEW,
            body="",
            title="Retrospective reviews",
            publication="AllMusic",
            rating=Rating(value=4.5, scale=5),
            language="en",
            scope=Scope.RELEASE,
            sources=SOURCE,
        ),
        Text(kind=TextKind.REVIEW, body="", scope=Scope.RELEASE, sources=[Provenance(source="x")]),
        Text(
            kind=TextKind.WIKI,
            body="No score.",
            rating=Rating(),
            scope=Scope.RELEASE,
            sources=SOURCE,
        ),
    ]
    partial = Partial(
        source="bandcamp",
        candidate=record,
        tags=[Tag(name="dubstep", weight=0.75, scope=Scope.RELEASE, sources=SOURCE)],
        credits=[
            Credit(
                role="Producer",
                name="Burial",
                detail="all tracks",
                scope=Scope.RELEASE,
                sources=SOURCE,
            ),
        ],
        texts=texts,
        relations=[
            Relation(
                kind=RelationKind.LABEL,
                target=Entity(type=EntityType.LABEL, name="Hyperdub", url="https://hyperdub.net"),
                note="founded by Kode9",
                scope=Scope.LABEL,
                sources=SOURCE,
            ),
            Relation(
                kind=RelationKind.SIMILAR,
                target=Entity(type=EntityType.RELEASE, name="Rival Dealer", artist="Burial"),
                scope=Scope.RELEASE,
                sources=SOURCE,
            ),
        ],
        metrics=[
            Metric(kind=MetricKind.LISTENS, value=1200, scope=Scope.RELEASE_GROUP, sources=SOURCE),
            Metric(
                kind=MetricKind.LISTENERS,
                value=0.5,
                scale=1,
                scope=Scope.RELEASE,
                sources=SOURCE,
            ),
        ],
        links=[
            Link(
                service="bandcamp",
                url=SOURCE[0].url or "",
                target=LinkTarget.ALBUM,
                sources=SOURCE,
            ),
        ],
    )
    second = Partial(source="discogs", candidate=other)
    error = AdapterError(source="lastfm", kind=ErrorKind.SKIPPED, reason="no API key")

    return to_markdown(merge(query, [partial, second], [error], generated_at=NOW))


def test_markdown_sections_and_sources() -> None:
    text = untrue_dossier()

    assert text.startswith("# Burial — Untrue (Deluxe)\n")
    for heading in (
        "## Identity",
        "## Tags",
        "## Credits",
        "## Texts",
        "## Relations",
        "## Metrics",
        "## Links",
        "## Errors",
    ):
        assert f"\n{heading}\n" in text
    assert "- **Version:** reissue (Deluxe)" in text
    assert (
        "- **Label:** Hyperdub, HDBCD002 ([bandcamp](https://burial.bandcamp.com/album/untrue))"
        in text
    )
    assert (
        "- **Sources disagree on date:** 2007-11-05 "
        "([bandcamp](https://burial.bandcamp.com/album/untrue)); 2008 (discogs)" in text
    )
    assert "- dubstep (tag, release, 0.75) — [bandcamp]" in text
    assert "- Producer: Burial (all tracks)" in text
    assert "*review, release, Pitchfork, Critic — 9/10*" in text
    assert "> Rain on glass.\n>\n> Second paragraph." in text
    assert "*shop, release — A-*" in text
    assert "*user, release — 5*" in text
    assert "*wiki, release*" in text
    assert (
        "- AllMusic: 4.5/5 (Retrospective reviews, release, en) — "
        "[bandcamp](https://burial.bandcamp.com/album/untrue)\n" in text
    )
    assert "- Review (release) — x\n" in text
    assert "*label, release*" in text
    assert "- label: [Hyperdub](https://hyperdub.net) (founded by Kode9)" in text
    assert "- similar: Burial — Rival Dealer — [bandcamp]" in text
    assert "- lastfm: skipped — no API key" in text
    assert "- listens: 1200 (release_group) — [bandcamp]" in text
    assert "- listeners: 0.5/1 (release) — [bandcamp]" in text
    assert "**discogs_master:** 89497" in text
    assert "**ISRC:** GBAAA0700001" in text
    assert "**UPC:** 5055300315829" in text
    assert text.endswith("\n")


def test_markdown_of_empty_dossier_names_the_query() -> None:
    by_url = merge(Query(url="https://example.com/x"), [], generated_at=NOW)
    by_text = merge(parse_query("A - B", EntityKind.TRACK), [], generated_at=NOW)

    assert to_markdown(by_url) == "# https://example.com/x\n\n## Identity\n"
    assert to_markdown(by_text) == "# A - B\n\n## Identity\n\n- **Kind:** track\n"
