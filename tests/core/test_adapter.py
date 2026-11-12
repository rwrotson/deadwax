from deadwax.core import (
    ExternalId,
    Identity,
    IdKind,
    Link,
    LinkTarget,
    LookupContext,
    Provenance,
    Query,
    SourceState,
    SourceStatus,
)

SOURCES = [Provenance(source="musicbrainz")]


def test_context_prefers_query_ids_over_found_ones() -> None:
    query = Query(
        url="https://musicbrainz.org/recording/x", ids={IdKind.MUSICBRAINZ_RECORDING: "q"}
    )
    identity = Identity(
        external_ids=[
            ExternalId(kind=IdKind.MUSICBRAINZ_RECORDING, value="found", sources=SOURCES),
            ExternalId(kind=IdKind.WIKIDATA, value="Q1", sources=SOURCES),
        ]
    )
    context = LookupContext(query=query, identity=identity)

    assert context.id(IdKind.MUSICBRAINZ_RECORDING) == "q"
    assert context.id(IdKind.WIKIDATA) == "Q1"
    assert context.id(IdKind.DISCOGS_MASTER) is None


def test_context_lists_links_of_a_service() -> None:
    links = [
        Link(service="spotify", url="https://s/1", target=LinkTarget.TRACK, sources=SOURCES),
        Link(service="deezer", url="https://d/1", target=LinkTarget.TRACK, sources=SOURCES),
    ]
    context = LookupContext(query=Query(url="https://s/1"), links=links)

    assert context.urls("spotify") == ["https://s/1"]
    assert context.urls("tidal") == []


def test_status_is_ready_only_in_the_ready_state() -> None:
    assert SourceStatus(source="a", state=SourceState.READY).ready
    assert not SourceStatus(source="a", state=SourceState.MISSING_CREDENTIAL).ready
