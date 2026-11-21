import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from deadwax.core import (
    Adapter,
    BlockedError,
    Capability,
    ConfigurationError,
    EntityKind,
    ErrorKind,
    IdKind,
    Link,
    LinkTarget,
    LookupContext,
    LookupOptions,
    Lookups,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RateLimitedError,
    RecordCandidate,
    Requirement,
    Scope,
    SourceError,
    SourceGroup,
    SourceState,
    SourceStatus,
    Tag,
    adapter_time_left,
    expand_names,
    pause_adapter_timeout,
    run,
    text_query,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 12, tzinfo=UTC)
TRACK = text_query("Everything but the Girl - Missing", EntityKind.TRACK)

type Behaviour = Callable[[Query, LookupContext], Awaitable[Partial]]


@dataclass
class FakeAdapter:
    name: str
    pass_: Pass = Pass.ENRICH
    behaviour: Behaviour | None = None
    state: SourceState = SourceState.READY
    detail: str | None = None
    resolves_urls: bool = False
    capabilities: frozenset[Capability] = frozenset({Capability.TAGS})
    requires: tuple[Requirement, ...] = ()
    group: SourceGroup = SourceGroup.CORE
    kinds: frozenset[EntityKind] = frozenset(EntityKind)
    unresolved: bool = True
    calls: list[tuple[Query, LookupContext]] = field(default_factory=list)

    @property
    def lookups(self) -> Lookups:
        return Lookups(
            track=self.lookup if EntityKind.TRACK in self.kinds else None,
            album=self.lookup if EntityKind.ALBUM in self.kinds else None,
            unresolved=self.lookup if self.unresolved else None,
        )

    def status(self) -> SourceStatus:
        return SourceStatus(source=self.name, state=self.state, detail=self.detail)

    def resolves(self, query: Query) -> bool:
        return self.resolves_urls

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        self.calls.append((query, context))
        if self.behaviour is not None:
            return await self.behaviour(query, context)
        return found(self.name)


def found(source: str, title: str = "Missing", **fields: object) -> Partial:
    values: dict[str, object] = {"artist": "Everything but the Girl", "title": title}
    return Partial(
        source=source,
        candidate=RecordCandidate.model_validate(values | fields),
        tags=[Tag(name=source, scope=Scope.RECORDING, sources=[Provenance(source=source)])],
    )


def returning(partial: Partial) -> Behaviour:
    async def behaviour(query: Query, context: LookupContext) -> Partial:
        return partial

    return behaviour


def raising(error: BaseException) -> Behaviour:
    async def behaviour(query: Query, context: LookupContext) -> Partial:
        raise error

    return behaviour


async def lookup(
    adapters: list[FakeAdapter],
    query: Query = TRACK,
    options: LookupOptions | None = None,
) -> list[str]:
    protocol_adapters: list[Adapter] = list(adapters)
    dossier = await run(query, protocol_adapters, options, now=lambda: NOW)
    return [f"{e.source}:{e.kind}" for e in dossier.errors]


async def test_identity_pass_runs_before_enrichment_and_feeds_its_context() -> None:
    identity_partial = found("musicbrainz", ids={IdKind.WIKIDATA: "Q1"})
    identity_partial = identity_partial.model_copy(
        update={
            "links": [
                Link(
                    service="spotify",
                    url="https://open.spotify.com/track/1",
                    target=LinkTarget.TRACK,
                    sources=[Provenance(source="musicbrainz")],
                ),
            ],
        },
    )
    musicbrainz = FakeAdapter("musicbrainz", Pass.IDENTITY, returning(identity_partial))
    wikipedia = FakeAdapter("wikipedia")

    dossier = await run(TRACK, [wikipedia, musicbrainz], now=lambda: NOW)

    [(_, first_context)] = musicbrainz.calls
    [(_, context)] = wikipedia.calls
    assert first_context.identity.title is None
    assert context.id(IdKind.WIKIDATA) == "Q1"
    assert context.urls("spotify") == ["https://open.spotify.com/track/1"]
    assert [tag.name for tag in dossier.tags] == ["musicbrainz", "wikipedia"]
    assert dossier.generated_at == NOW


async def test_links_pass_runs_after_enrichment_and_sees_its_links() -> None:
    itunes_partial = found("itunes").model_copy(
        update={
            "links": [
                Link(
                    service="apple_music",
                    url="https://music.apple.com/us/album/x/1?i=2",
                    target=LinkTarget.TRACK,
                    sources=[Provenance(source="itunes")],
                ),
            ],
        },
    )
    itunes = FakeAdapter("itunes", Pass.ENRICH, returning(itunes_partial))
    odesli = FakeAdapter("odesli", Pass.LINKS)

    await run(TRACK, [odesli, itunes], now=lambda: NOW)

    [(_, context)] = odesli.calls
    assert context.urls("apple_music") == ["https://music.apple.com/us/album/x/1?i=2"]


async def test_other_version_found_in_identity_pass_gives_no_context() -> None:
    remix = found("musicbrainz", "Missing (Todd Terry Remix)", ids={IdKind.WIKIDATA: "Q2"})
    musicbrainz = FakeAdapter("musicbrainz", Pass.IDENTITY, returning(remix))
    wikipedia = FakeAdapter("wikipedia")

    await run(TRACK, [musicbrainz, wikipedia], now=lambda: NOW)

    [(_, context)] = wikipedia.calls
    assert context.id(IdKind.WIKIDATA) is None


async def test_url_resolver_runs_first_and_sets_the_kind() -> None:
    query = Query(url="https://artist.bandcamp.com/x")
    page = found("bandcamp", kind=EntityKind.ALBUM, url="https://artist.bandcamp.com/x")
    bandcamp = FakeAdapter("bandcamp", Pass.ENRICH, returning(page), resolves_urls=True)
    musicbrainz = FakeAdapter("musicbrainz", Pass.IDENTITY)

    dossier = await run(query, [musicbrainz, bandcamp], now=lambda: NOW)

    [(passed_query, context)] = musicbrainz.calls
    assert len(bandcamp.calls) == 1
    assert passed_query.kind is EntityKind.ALBUM
    assert context.identity.title is not None
    assert context.identity.title.value == "Missing"
    assert dossier.query == query
    assert dossier.identity.kind is EntityKind.ALBUM


async def test_resolver_without_kind_leaves_the_query_unchanged() -> None:
    query = Query(url="https://song.link/x")
    odesli = FakeAdapter(
        "odesli",
        Pass.IDENTITY,
        returning(Partial(source="odesli")),
        resolves_urls=True,
    )
    discogs = FakeAdapter("discogs")

    await run(query, [odesli, discogs], now=lambda: NOW)

    [(passed_query, _)] = discogs.calls
    assert passed_query.kind is None


async def test_kind_given_by_the_url_is_kept() -> None:
    query = Query(url="https://artist.bandcamp.com/track/x", kind=EntityKind.TRACK)
    page = found("bandcamp", kind=EntityKind.ALBUM)
    bandcamp = FakeAdapter("bandcamp", Pass.ENRICH, returning(page), resolves_urls=True)
    discogs = FakeAdapter("discogs")

    await run(query, [bandcamp, discogs], now=lambda: NOW)

    [(passed_query, _)] = discogs.calls
    assert passed_query.kind is EntityKind.TRACK


async def test_text_query_has_no_resolver() -> None:
    bandcamp = FakeAdapter("bandcamp", resolves_urls=True)

    await run(TRACK, [bandcamp], now=lambda: NOW)

    assert len(bandcamp.calls) == 1


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (BlockedError("challenge", url="https://x/1"), ErrorKind.BLOCKED),
        (RateLimitedError("slow down"), ErrorKind.RATE_LIMITED),
        (NotFoundError("gone"), ErrorKind.NOT_FOUND),
        (SourceError("HTTP 500"), ErrorKind.FAILED),
        (ValueError("bad json"), ErrorKind.FAILED),
    ],
)
async def test_failures_become_errors_and_others_continue(
    error: Exception,
    kind: ErrorKind,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = FakeAdapter("discogs", behaviour=raising(error))
    working = FakeAdapter("lastfm")

    with caplog.at_level(logging.WARNING, logger="deadwax"):
        dossier = await run(TRACK, [broken, working], now=lambda: NOW)

    [failure] = dossier.errors
    assert (failure.source, failure.kind) == ("discogs", kind)
    assert str(error) in failure.reason
    assert [tag.name for tag in dossier.tags] == ["lastfm"]
    if isinstance(error, SourceError):
        assert failure.url == error.url
    else:
        assert "ValueError" in failure.reason
        assert "discogs failed" in caplog.text


async def test_slow_adapter_times_out() -> None:
    async def slow(query: Query, context: LookupContext) -> Partial:
        await asyncio.sleep(10)
        raise AssertionError("not reached")  # pragma: no cover

    options = LookupOptions(adapter_timeout=10, adapter_timeouts={"bandcamp": 0.01})

    errors = await lookup([FakeAdapter("bandcamp", behaviour=slow)], options=options)

    assert errors == ["bandcamp:timeout"]


async def test_cancellation_propagates() -> None:
    adapter = FakeAdapter("bandcamp", behaviour=raising(asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        await lookup([adapter])


async def test_unready_adapters_are_skipped_and_disabled_ones_are_silent() -> None:
    missing_key = FakeAdapter(
        "lastfm",
        state=SourceState.MISSING_CREDENTIAL,
        detail="needs sources.lastfm.api_key",
    )
    missing_extra = FakeAdapter("bandcamp", state=SourceState.MISSING_EXTRA)
    disabled = FakeAdapter("discogs", state=SourceState.DISABLED)

    dossier = await run(TRACK, [missing_key, missing_extra, disabled], now=lambda: NOW)

    assert [(e.source, e.kind, e.reason) for e in dossier.errors] == [
        ("lastfm", ErrorKind.SKIPPED, "needs sources.lastfm.api_key"),
        ("bandcamp", ErrorKind.SKIPPED, "missing_extra"),
    ]
    assert [missing_key.calls, missing_extra.calls, disabled.calls] == [[], [], []]


async def test_include_and_exclude_select_adapters_without_errors() -> None:
    adapters = [
        FakeAdapter("musicbrainz", Pass.IDENTITY),
        FakeAdapter("discogs"),
        FakeAdapter("lastfm"),
    ]
    options = LookupOptions(
        include=frozenset({"musicbrainz", "discogs"}),
        exclude=frozenset({"discogs"}),
    )

    errors = await lookup(adapters, options=options)

    assert errors == []
    assert [len(adapter.calls) for adapter in adapters] == [1, 0, 0]


async def test_unknown_source_names_are_rejected() -> None:
    options = LookupOptions(exclude=frozenset({"spotify"}))

    with pytest.raises(
        ConfigurationError,
        match="unknown sources: spotify; known: lastfm; groups: core, shops, ",
    ):
        await lookup([FakeAdapter("lastfm")], options=options)


def grouped() -> list[FakeAdapter]:
    return [
        FakeAdapter("musicbrainz", Pass.IDENTITY),
        FakeAdapter("juno", group=SourceGroup.SHOPS),
        FakeAdapter("boomkat", group=SourceGroup.SHOPS),
        FakeAdapter("kexp", group=SourceGroup.RADIO),
    ]


async def test_a_group_in_include_runs_only_its_members() -> None:
    adapters = grouped()

    errors = await lookup(adapters, options=LookupOptions(include=frozenset({"shops"})))

    assert errors == []
    assert [len(adapter.calls) for adapter in adapters] == [0, 1, 1, 0]


async def test_all_in_include_runs_every_ready_source_except_excluded_ones() -> None:
    adapters = grouped()

    await lookup(
        adapters,
        options=LookupOptions(include=frozenset({"all"}), exclude=frozenset({"boomkat"})),
    )

    assert [len(adapter.calls) for adapter in adapters] == [1, 1, 0, 1]


async def test_shared_resource_wait_does_not_consume_adapter_timeout() -> None:
    lock = asyncio.Lock()
    await lock.acquire()

    async def release() -> None:
        await asyncio.sleep(0.05)
        lock.release()

    async def wait_for_resource(query: Query, context: LookupContext) -> Partial:
        async with pause_adapter_timeout():
            await lock.acquire()
        try:
            await asyncio.sleep(0.005)
            return found("waiting")
        finally:
            lock.release()

    async with asyncio.TaskGroup() as group:
        group.create_task(release())
        result = group.create_task(
            lookup(
                [FakeAdapter("waiting", behaviour=wait_for_resource)],
                options=LookupOptions(adapter_timeout=0.03),
            ),
        )

    assert result.result() == []


async def test_adapter_time_left_counts_down_inside_an_adapter() -> None:
    seen: list[float | None] = []

    async def measure(query: Query, context: LookupContext) -> Partial:
        seen.append(adapter_time_left())
        return found("measuring")

    errors = await lookup(
        [FakeAdapter("measuring", behaviour=measure)],
        options=LookupOptions(adapter_timeout=30),
    )

    assert errors == []
    [left] = seen
    assert left is not None
    assert 0 < left <= 30
    assert adapter_time_left() is None


async def test_a_group_in_exclude_removes_its_members() -> None:
    adapters = grouped()

    await lookup(adapters, options=LookupOptions(exclude=frozenset({"shops"})))

    assert [len(adapter.calls) for adapter in adapters] == [1, 0, 0, 1]


async def test_source_and_group_names_combine() -> None:
    adapters = grouped()
    options = LookupOptions(
        include=frozenset({"core", "shops", "kexp"}),
        exclude=frozenset({"boomkat"}),
    )

    await lookup(adapters, options=options)

    assert [len(adapter.calls) for adapter in adapters] == [1, 1, 0, 1]


async def test_expand_names_maps_groups_to_their_sources() -> None:
    adapters: list[Adapter] = list(grouped())

    assert expand_names(["shops", "musicbrainz"], adapters) == {"juno", "boomkat", "musicbrainz"}
    assert expand_names(["samples"], adapters) == frozenset()
    assert expand_names(["all"], adapters) == {adapter.name for adapter in adapters}
    assert expand_names(["all", "shops"], adapters) == {adapter.name for adapter in adapters}
    with pytest.raises(ConfigurationError, match="unknown sources: nonsense"):
        expand_names(["all", "nonsense"], adapters)
    with pytest.raises(ConfigurationError, match="unknown sources: nts"):
        expand_names(["nts"], adapters)


def counting(running: list[int], peak: list[int]) -> Behaviour:
    async def behaviour(query: Query, context: LookupContext) -> Partial:
        running.append(1)
        peak[0] = max(peak[0], len(running))
        await asyncio.sleep(0.01)
        running.pop()
        return Partial(source="counted")

    return behaviour


@pytest.mark.parametrize(("concurrency", "expected"), [(2, 2), (None, 5)])
async def test_concurrency_caps_adapters_running_at_once(
    concurrency: int | None,
    expected: int,
) -> None:
    running: list[int] = []
    peak = [0]
    adapters = [FakeAdapter(f"s{i}", behaviour=counting(running, peak)) for i in range(5)]

    errors = await lookup(adapters, options=LookupOptions(concurrency=concurrency))

    assert errors == []
    assert all(len(adapter.calls) == 1 for adapter in adapters)
    assert peak == [expected]


async def test_waiting_for_a_slot_does_not_count_toward_the_timeout() -> None:
    async def slow(query: Query, context: LookupContext) -> Partial:
        await asyncio.sleep(0.2)
        return found("first")

    adapters = [FakeAdapter("first", behaviour=slow), FakeAdapter("second")]
    options = LookupOptions(concurrency=1, adapter_timeouts={"second": 0.1})

    errors = await lookup(adapters, options=options)

    assert errors == []
    assert len(adapters[1].calls) == 1


async def test_no_adapters_gives_an_empty_dossier() -> None:
    dossier = await run(TRACK, [], now=lambda: NOW)

    assert not dossier.found
    assert dossier.errors == []


async def test_default_clock_is_aware() -> None:
    dossier = await run(TRACK, [])

    assert dossier.generated_at.tzinfo is not None


type Traced = Callable[[str], list[dict[str, object]]]


async def test_lookup_traces_selection_passes_and_adapter_outcomes(traced: Traced) -> None:
    other = found("discogs", title="Driving")
    adapters = [
        FakeAdapter("musicbrainz", Pass.IDENTITY),
        FakeAdapter("discogs", behaviour=returning(other)),
        FakeAdapter("lastfm", behaviour=raising(NotFoundError("no page", url="https://x"))),
        FakeAdapter("bandcamp", state=SourceState.MISSING_EXTRA),
        FakeAdapter("kexp"),
    ]
    options = LookupOptions(exclude=frozenset({"kexp"}))

    await lookup(adapters, options=options)

    [selected] = traced("lookup.selected")
    assert selected["ready"] == ["musicbrainz", "discogs", "lastfm"]
    assert selected["skipped"] == {"bandcamp": "missing_extra"}
    assert selected["not_selected"] == ["kexp"]
    assert [(e["pass"], e["sources"]) for e in traced("pass.start")] == [
        ("identity", ["musicbrainz"]),
        ("enrich", ["discogs", "lastfm"]),
    ]
    ends = {event["source"]: event for event in traced("adapter.end")}
    assert ends["musicbrainz"]["outcome"] == "ok"
    assert ends["musicbrainz"]["pass"] == "identity"
    assert ends["musicbrainz"]["facts"] == {
        "tags": 1,
        "credits": 0,
        "texts": 0,
        "relations": 0,
        "metrics": 0,
        "links": 0,
    }
    assert ends["lastfm"]["outcome"] == "error"
    assert ends["lastfm"]["errors"] == [
        {"kind": "not_found", "reason": "no page", "url": "https://x"},
    ]
    judged = {(e["source"], e["stage"]): e["verdict"] for e in traced("merge.judge")}
    assert judged[("musicbrainz", "context")] == "match"
    assert judged[("discogs", "final")] == "no_match"
    compared = [e for e in traced("match.compare") if e.get("source") == "discogs"]
    assert compared[-1]["failed"] == ["title"]


async def test_url_lookup_traces_its_resolver_and_adopted_kind(traced: Traced) -> None:
    query = Query(url="https://artist.bandcamp.com/x")
    page = found("bandcamp", kind=EntityKind.ALBUM)
    bandcamp = FakeAdapter("bandcamp", Pass.ENRICH, returning(page), resolves_urls=True)

    await lookup([bandcamp], query)

    assert traced("lookup.resolver") == [{"source": "bandcamp"}]
    assert traced("lookup.kind_adopted") == [{"kind": "album"}]
    assert [e["pass"] for e in traced("adapter.end")] == ["resolve"]


async def test_facets_select_adapters_that_contribute_them() -> None:
    musicbrainz = FakeAdapter("musicbrainz", Pass.IDENTITY, capabilities=frozenset())
    lastfm = FakeAdapter("lastfm", capabilities=frozenset({Capability.TAGS}))
    genius = FakeAdapter(
        "genius",
        capabilities=frozenset({Capability.IDENTITY, Capability.TEXTS}),
        state=SourceState.MISSING_CREDENTIAL,
    )
    odesli = FakeAdapter("odesli", Pass.LINKS, capabilities=frozenset({Capability.LINKS}))
    options = LookupOptions(facets=frozenset({Capability.IDENTITY, Capability.TAGS}))

    errors = await lookup([musicbrainz, lastfm, genius, odesli], options=options)

    assert (len(musicbrainz.calls), len(lastfm.calls), len(odesli.calls)) == (1, 1, 0)
    assert errors == []
    [(_, context)] = lastfm.calls
    assert context.wants(Capability.TAGS)
    assert not context.wants(Capability.LINKS)


async def test_facets_keep_the_resolver_of_a_url_query() -> None:
    query = Query(url="https://song.link/x")
    odesli = FakeAdapter(
        "odesli",
        Pass.LINKS,
        capabilities=frozenset({Capability.LINKS}),
        resolves_urls=True,
    )
    options = LookupOptions(facets=frozenset({Capability.TAGS}))

    await lookup([odesli], query, options)

    assert len(odesli.calls) == 1


async def test_without_facets_every_adapter_runs_and_wants_everything() -> None:
    silent = FakeAdapter("silent", capabilities=frozenset())

    await lookup([silent])

    [(_, context)] = silent.calls
    assert context.wants(Capability.METRICS)


async def test_adapters_without_a_lookup_of_the_query_kind_do_not_run(traced: Traced) -> None:
    album = text_query("Everything but the Girl - Walking Wounded", EntityKind.ALBUM)
    lastfm = FakeAdapter("lastfm", behaviour=returning(found("lastfm", title="Walking Wounded")))
    genius = FakeAdapter("genius", kinds=frozenset({EntityKind.TRACK}))

    errors = await lookup([lastfm, genius], album)

    assert (len(lastfm.calls), len(genius.calls)) == (1, 0)
    assert errors == []
    [selected] = traced("lookup.selected")
    assert selected["unsupported"] == ["genius"]
    assert selected["not_selected"] == []


async def test_each_pass_dispatches_on_the_kind_known_so_far(traced: Traced) -> None:
    query = Query(url="https://example.org/x")
    page = found("musicbrainz", kind=EntityKind.ALBUM)
    musicbrainz = FakeAdapter("musicbrainz", Pass.IDENTITY, returning(page))
    lastfm = FakeAdapter("lastfm", unresolved=False)
    genius = FakeAdapter("genius", kinds=frozenset({EntityKind.TRACK}))

    await lookup([musicbrainz, lastfm, genius], query)

    assert (len(musicbrainz.calls), len(lastfm.calls), len(genius.calls)) == (1, 1, 0)
    starts = {event["pass"]: event for event in traced("pass.start")}
    assert starts["identity"]["kind"] is None
    assert starts["enrich"]["kind"] == "album"
    assert starts["enrich"]["sources"] == ["lastfm"]
    assert starts["enrich"]["unsupported"] == ["genius"]


async def test_a_resolver_needs_a_lookup_of_an_unknown_kind() -> None:
    query = Query(url="https://artist.bandcamp.com/x")
    tracks_only = FakeAdapter("shop", resolves_urls=True, unresolved=False)
    bandcamp = FakeAdapter("bandcamp", resolves_urls=True)

    await lookup([tracks_only, bandcamp], query)

    assert (len(tracks_only.calls), len(bandcamp.calls)) == (0, 1)
