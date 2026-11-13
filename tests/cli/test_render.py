import json
from pathlib import Path

import pytest
from rich.console import Console

from deadwax import (
    Capability,
    Dossier,
    Pass,
    Query,
    Requirement,
    SourceGroup,
    SourceInfo,
    SourceState,
    SourceStatus,
)
from deadwax.cli.render import (
    OutputFormat,
    env_variable,
    print_dossier,
    print_run,
    print_runs,
    print_sources,
)
from deadwax.logs import RunRecord


def rendered(dossier: Dossier, output: OutputFormat = OutputFormat.PRETTY) -> str:
    console = Console(record=True, width=1000)
    print_dossier(dossier, output, console)
    return console.export_text()


def test_pretty_dossier_shows_every_section_with_sources(dossier: Dossier) -> None:
    text = rendered(dossier)

    assert text.startswith("Everything but the Girl — Missing")
    sections = ("Identity", "Tags", "Credits", "Texts", "Relations", "Metrics", "Links", "Errors")
    for section in sections:
        assert f"\n{section}\n" in text
    assert "remix (Todd Terry remix)" in text
    assert "Blanco y Negro, NEG84CD" in text
    assert "℗ 1995 Blanco y Negro" in text
    assert "sources disagree on date: 1995 (musicbrainz) ≠ 1994 (itunes)" in text
    assert "recording genres: house — musicbrainz" in text
    assert "review · Missing · Example Weekly · A. Critic · 1995-10-01 · rating 4/5" in text
    assert "rating B+" in text
    assert "x" * 600 + "…" in text
    assert "x" * 601 not in text
    assert "remix of\n  Missing (the song this recording performs) — musicbrainz" in text
    assert "Now 32 (Various, 1995)" in text
    assert "blocked" in text
    assert "listens    3,099,604  recording" in text
    assert "4.5/10" in text


def test_each_source_is_named_once_per_fact(dossier: Dossier) -> None:
    assert "musicbrainz, itunes" in rendered(dossier)


def test_nothing_matched(dossier: Dossier) -> None:
    empty = Dossier(
        query=Query(url="https://example.org/x"),
        identity={},  # type: ignore[arg-type]
        generated_at=dossier.generated_at,
    )

    assert rendered(empty).strip() == "Nothing matched the query"


def test_untitled_artist_is_omitted(dossier: Dossier) -> None:
    identity = dossier.identity.model_copy(update={"artist": None})

    assert rendered(dossier.model_copy(update={"identity": identity})).startswith("Missing\n")


def test_json_and_markdown(dossier: Dossier) -> None:
    assert Dossier.model_validate_json(rendered(dossier, OutputFormat.JSON)) == dossier
    assert rendered(dossier, OutputFormat.MARKDOWN).startswith(
        "# Everything but the Girl — Missing",
    )


INFOS = [
    SourceInfo(
        source="musicbrainz",
        group=SourceGroup.CORE,
        default=True,
        pass_=Pass.IDENTITY,
        capabilities=[Capability.IDENTITY, Capability.LINKS],
        requires=[],
        status=SourceStatus(source="musicbrainz", state=SourceState.READY),
    ),
    SourceInfo(
        source="lastfm",
        group=SourceGroup.CORE,
        default=True,
        pass_=Pass.ENRICH,
        capabilities=[Capability.TAGS],
        requires=[Requirement(setting="lastfm.api_key", purpose="every lookup")],
        status=SourceStatus(source="lastfm", state=SourceState.MISSING_CREDENTIAL, detail="x"),
    ),
    SourceInfo(
        source="bandcamp",
        group=SourceGroup.CORE,
        default=True,
        pass_=Pass.ENRICH,
        capabilities=[],
        requires=[],
        status=SourceStatus(
            source="bandcamp",
            state=SourceState.MISSING_EXTRA,
            detail="deadwax[browser]",
        ),
    ),
    SourceInfo(
        source="itunes",
        group=SourceGroup.CORE,
        default=False,
        pass_=Pass.ENRICH,
        capabilities=[],
        requires=[],
        status=SourceStatus(source="itunes", state=SourceState.DISABLED),
    ),
]


@pytest.mark.parametrize("output", list(OutputFormat))
def test_sources(output: OutputFormat) -> None:
    console = Console(record=True, width=200)

    print_sources(INFOS, output, console)
    text = console.export_text()

    if output is OutputFormat.JSON:
        assert [row["source"] for row in json.loads(text)] == [
            "musicbrainz",
            "lastfm",
            "bandcamp",
            "itunes",
        ]
        assert {(row["group"], row["default"]) for row in json.loads(text)} == {
            ("core", True),
            ("core", False),
        }
    else:
        assert "missing DEADWAX_LASTFM__API_KEY" in text
        assert "missing extra: deadwax[browser]" in text
        assert "disabled" in text
        assert "identity, links" in text
        assert "core" in text
        assert "yes" in text


def test_env_variable() -> None:
    assert env_variable("discogs.token") == "DEADWAX_DISCOGS__TOKEN"


KEY = {"artist": "Everything but the Girl", "title": "Missing", "version": "original"}
REMIX = {"artist": "Everything but the Girl", "title": "Missing", "version": "remix: Todd Terry"}
EVENTS: list[dict[str, object]] = [
    {"event": "run.start", "argv": ["--track", "a - b"], "version": "1", "python": "3.14"},
    {"event": "run.settings", "settings": {}},
    {"event": "query.parsed", "query": {"kind": "track", "artist": "a", "title": "b"}},
    {"event": "lookup.selected", "ready": ["musicbrainz"], "skipped": {"lastfm": "needs key"}},
    {"event": "pass.start", "pass": "identity", "sources": ["musicbrainz"], "identity": {}},
    {"event": "pass.start", "pass": "enrich", "sources": ["discogs"], "identity": KEY, "links": 2},
    {
        "event": "http.request",
        "source": "musicbrainz",
        "method": "GET",
        "url": "https://mb/x",
        "status": 200,
        "cache": "miss",
        "attempts": 1,
        "duration_ms": 120,
        "bytes": 512,
    },
    {
        "event": "http.request",
        "source": "deezer",
        "method": "GET",
        "url": "https://dz/x",
        "cache": "off",
        "attempts": 3,
        "duration_ms": 900,
        "error": {"type": "TransportError", "message": "ConnectError: refused"},
    },
    {
        "event": "match.compare",
        "source": "discogs",
        "reference": KEY,
        "candidate": REMIX,
        "artist_score": 1.0,
        "title_score": 0.4,
        "verdict": "no_match",
        "failed": ["title"],
    },
    {"event": "match.compare", "stage": "context", "candidate": KEY, "verdict": "match"},
    {"event": "merge.reference", "stage": "final", "reference": KEY, "partials": 3},
    {"event": "merge.reference", "stage": "final", "reference": None, "partials": 1},
    {"event": "match.compare", "stage": "final", "candidate": KEY, "verdict": "match"},
    {
        "event": "http.retry",
        "source": "musicbrainz",
        "url": "https://mb/x",
        "status": 503,
        "delay_s": 1,
    },
    {"event": "http.retry", "source": "deezer", "url": "https://dz/x", "error": "refused"},
    {
        "event": "http.challenge",
        "source": "deezer",
        "url": "https://dz/x",
        "challenge": "Akamai block",
        "fetcher": "httpx",
    },
    {"event": "search.pick", "source": "bandcamp", "hits": [{"url": "/a"}], "picked": "/a"},
    {"event": "search.ranked", "query": "recording:x", "matched": [], "picked": None},
    {
        "event": "adapter.end",
        "source": "musicbrainz",
        "duration_ms": 1500,
        "errors": [],
        "candidate": KEY,
        "facts": {"tags": 3, "links": 0},
    },
    {"event": "adapter.end", "source": "kexp", "errors": [], "candidate": None, "facts": {}},
    {
        "event": "adapter.end",
        "source": "deezer",
        "errors": [{"kind": "blocked", "reason": "Akamai", "url": "https://dz/x"}],
    },
    {"event": "merge.judge", "source": "discogs", "verdict": "other_version", "title_score": 1},
    {"event": "slow answer", "level": "warning", "logger": "httpx", "source": "deezer"},
    {"event": "unexpected Bandcamp date", "level": "debug", "value": "x"},
    {"event": "run.crash", "level": "debug", "exception": "Traceback\nRuntimeError: boom"},
    {
        "event": "run.end",
        "summary": {
            "outcome": "ok",
            "duration_ms": 2000,
            "identity": "Everything but the Girl - Missing",
            "errors": [{"source": "deezer", "kind": "blocked", "reason": "Akamai"}],
        },
    },
]


def rendered_run(output: OutputFormat = OutputFormat.PRETTY, *, full: bool = False) -> str:
    console = Console(record=True, width=300)
    print_run(EVENTS, output, console, full=full)
    return console.export_text()


def test_run_timeline_explains_each_step() -> None:
    text = rendered_run()

    for line in (
        "deadwax --track a - b  deadwax 1, Python 3.14",
        "query: a - b (track)",
        "sources: musicbrainz\nskipped: lastfm (needs key)",
        "pass identity: musicbrainz",
        "context: Everything but the Girl - Missing, 2 links",
        "[musicbrainz] GET https://mb/x → 200 (cache miss, 1 attempts, 0.12 s, 512 B)",
        "[deezer] GET https://dz/x → TransportError (cache off, 3 attempts, 0.90 s, Connect",
        "[discogs] compared with Everything but the Girl - Missing\n  [discogs] compare Every",
        "Missing [remix: Todd Terry] → no_match (artist 1.00, title 0.40; failed title)",
        "[musicbrainz] retry https://mb/x after HTTP 503, waiting 1.0 s",
        "[deezer] retry https://dz/x after refused",
        "[deezer] Akamai block via httpx: https://dz/x",
        "[bandcamp] search: 1 kept, picked /a",
        "search for recording:x: 0 kept, picked nothing",
        "[musicbrainz] ok: Everything but the Girl - Missing (1.50 s; 3 tags)",
        "[kexp] ok: no candidate (? s; no facts)",
        "[deezer] blocked: Akamai (? s, https://dz/x)",
        "[discogs] merge: other_version (artist ?, title 1.00)",
        '[deezer] slow answer {"logger": "httpx"}',
        'unexpected Bandcamp date {"value": "x"}',
        "RuntimeError: boom",
        "merge of 3 results against Everything but the Girl - Missing",
        "merge of 1 results against the first candidate",
        "ok in 2.00 s: Everything but the Girl - Missing\n  deezer: blocked — Akamai",
    ):
        assert line in text
    assert "run.settings" not in text
    assert text.count("compare ") == 1


def test_run_timeline_formats() -> None:
    assert rendered_run(full=True).count("compare ") == 3
    assert rendered_run(OutputFormat.MARKDOWN).startswith("```\ndeadwax --track")
    assert json.loads(rendered_run(OutputFormat.JSON)) == EVENTS


def run_record(**fields: object) -> RunRecord:
    values: dict[str, object] = {
        "run_id": "20261113T100000Z-aaa111",
        "started_at": "2026-11-13T10:00:00Z",
        "duration_ms": 1500,
        "command": "lookup",
        "argv": ["sources"],
        "version": "1",
        "outcome": "crash",
        "sources": {"itunes": "ok", "deezer": "blocked"},
        "file": "runs/x.jsonl",
    }
    return RunRecord.model_validate(values | fields)


@pytest.mark.parametrize("output", list(OutputFormat))
def test_runs(output: OutputFormat) -> None:
    console = Console(record=True, width=300)

    print_runs([run_record(), run_record(query="A - B", outcome="ok")], output, Path("j"), console)

    text = console.export_text()
    if output is OutputFormat.JSON:
        assert [run["outcome"] for run in json.loads(text)] == ["crash", "ok"]
    else:
        assert "20261113T100000Z-aaa111" in text
        assert "2026-11-13 10:00" in text
        assert "deezer:blocked" in text
        assert "A - B" in text
        assert "sources" in text


def test_no_runs() -> None:
    console = Console(record=True)

    print_runs([], OutputFormat.PRETTY, Path("journal"), console)

    assert console.export_text() == "No runs journaled in journal.\n"
