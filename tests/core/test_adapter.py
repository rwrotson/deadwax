from deadwax.core import (
    EntityKind,
    ExternalId,
    Identity,
    IdKind,
    Link,
    LinkTarget,
    LookupContext,
    Lookups,
    Partial,
    Provenance,
    Query,
    Sourced,
    SourceState,
    SourceStatus,
    text_query,
)

SOURCES = [Provenance(source="musicbrainz")]


def test_context_prefers_query_ids_over_found_ones() -> None:
    query = Query(
        url="https://musicbrainz.org/recording/x",
        ids={IdKind.MUSICBRAINZ_RECORDING: "q"},
    )
    identity = Identity(
        external_ids=[
            ExternalId(kind=IdKind.MUSICBRAINZ_RECORDING, value="found", sources=SOURCES),
            ExternalId(kind=IdKind.WIKIDATA, value="Q1", sources=SOURCES),
        ],
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


def test_context_lists_the_query_isrc_first_without_repeats() -> None:
    query = text_query("Radiohead - Paranoid Android", EntityKind.TRACK, isrc="GBAYE9701376")
    identity = Identity(
        isrcs=[
            Sourced(value="GB-AYE-97-01376", sources=SOURCES),
            Sourced(value="GBAYE9700001", sources=SOURCES),
        ],
    )

    assert LookupContext(query=query, identity=identity).isrcs() == [
        "GBAYE9701376",
        "GBAYE9700001",
    ]
    assert LookupContext(query=query).isrcs() == ["GBAYE9701376"]
    assert LookupContext(query=Query(url="https://s/1")).isrcs() == []


async def _found(query: Query, context: LookupContext) -> Partial:
    return Partial(source="x")


def test_lookups_return_the_slot_of_a_kind_and_list_the_kinds_they_fill() -> None:
    lookups = Lookups(track=_found, unresolved=_found)

    assert lookups.get(EntityKind.TRACK) is _found
    assert lookups.get(EntityKind.ALBUM) is None
    assert lookups.get(None) is _found
    assert lookups.kinds == {EntityKind.TRACK}
    assert Lookups().kinds == frozenset()


def test_context_kind_comes_from_the_query_then_earlier_passes() -> None:
    url = Query(url="https://example.org/x")
    album = Identity(kind=EntityKind.ALBUM)
    track = text_query("A - B", EntityKind.TRACK)

    assert LookupContext(query=url).kind is None
    assert LookupContext(query=url, identity=album).kind is EntityKind.ALBUM
    assert LookupContext(query=track, identity=album).kind is EntityKind.TRACK
