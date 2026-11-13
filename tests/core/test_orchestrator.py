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
    SourceState,
    SourceStatus,
    Tag,
    parse_query,
    run,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 12, tzinfo=UTC)
TRACK = parse_query("Everything but the Girl - Missing", EntityKind.TRACK)

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
    calls: list[tuple[Query, LookupContext]] = field(default_factory=list)

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
        detail="needs lastfm.api_key",
    )
    missing_extra = FakeAdapter("bandcamp", state=SourceState.MISSING_EXTRA)
    disabled = FakeAdapter("discogs", state=SourceState.DISABLED)

    dossier = await run(TRACK, [missing_key, missing_extra, disabled], now=lambda: NOW)

    assert [(e.source, e.kind, e.reason) for e in dossier.errors] == [
        ("lastfm", ErrorKind.SKIPPED, "needs lastfm.api_key"),
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

    with pytest.raises(ConfigurationError, match="unknown sources: spotify; known: lastfm"):
        await lookup([FakeAdapter("lastfm")], options=options)


async def test_no_adapters_gives_an_empty_dossier() -> None:
    dossier = await run(TRACK, [], now=lambda: NOW)

    assert not dossier.found
    assert dossier.errors == []


async def test_default_clock_is_aware() -> None:
    dossier = await run(TRACK, [])

    assert dossier.generated_at.tzinfo is not None
