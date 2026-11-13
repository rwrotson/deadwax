import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from deadwax import (
    Dossier,
    Provenance,
    Relation,
    RelationKind,
    Sourced,
    SourceInfo,
    SourceState,
    Tag,
    to_markdown,
)
from deadwax.logs import RunRecord

# Longest text body shown in the terminal; JSON and Markdown keep the whole text.
_TEXT_LIMIT = 600


class OutputFormat(StrEnum):
    """How the command prints its result."""

    PRETTY = "pretty"
    JSON = "json"
    MARKDOWN = "markdown"


def env_variable(setting: str) -> str:
    """Name the environment variable of a setting path such as 'lastfm.api_key'."""
    return "DEADWAX_" + setting.upper().replace(".", "__")


def _sources(provenances: Iterable[Provenance]) -> Text:
    """Name each source once, linked to the first page it was found on."""
    first_urls: dict[str, str | None] = {}
    for provenance in provenances:
        if first_urls.get(provenance.source) is None:
            first_urls[provenance.source] = provenance.url
    text = Text(style="dim")
    for index, (source, url) in enumerate(first_urls.items()):
        if index:
            text.append(", ")
        text.append(source, style=f"link {url}" if url else "")
    return text


def _table(*columns: str) -> Table:
    table = Table(show_edge=False, box=None, pad_edge=False, expand=False)
    for column in columns:
        table.add_column(column, overflow="fold")
    return table


def _heading(title: str) -> Text:
    return Text(f"\n{title}", style="bold underline")


def _sourced(value: Sourced[str]) -> tuple[str, Text]:
    return value.value, _sources(value.sources)


def _identity_rows(dossier: Dossier) -> list[tuple[str, str, Text]]:
    identity = dossier.identity
    rows: list[tuple[str, str, Text]] = []
    if identity.kind is not None:
        rows.append(("kind", identity.kind.value, Text()))
    named = (("artist", identity.artist), ("title", identity.title))
    rows += [(name, *_sourced(value)) for name, value in named if value is not None]

    version = identity.version.kind.value
    if identity.version.detail:
        version = f"{version} ({identity.version.detail})"
    rows.append(("version", version, Text()))
    if identity.date is not None:
        rows.append(("date", *_sourced(identity.date)))

    for ref in identity.labels:
        name = f"{ref.name}, {ref.catalog_number}" if ref.catalog_number else ref.name
        rows.append(("label", name, _sources(ref.sources)))
    rows += [("ISRC", *_sourced(isrc)) for isrc in identity.isrcs]
    rows += [("UPC", *_sourced(upc)) for upc in identity.upcs]
    rows += [("copyright", *_sourced(line)) for line in identity.copyrights]
    rows += [(e.kind.value, e.value, _sources(e.sources)) for e in identity.external_ids]
    return rows


def _discrepancy(field: str, values: Sequence[Sourced[str]]) -> Text:
    line = Text(f"sources disagree on {field}: ", style="bold yellow")
    for index, value in enumerate(values):
        if index:
            line.append(" ≠ ", style="yellow")
        line.append(value.value, style="yellow")
        line.append(" (")
        line.append_text(_sources(value.sources))
        line.append(")")
    return line


def _identity(dossier: Dossier) -> list[Text | Table]:
    table = _table("", "", "")
    for row in _identity_rows(dossier):
        table.add_row(*row)
    parts: list[Text | Table] = [_heading("Identity"), table]
    parts += [_discrepancy(d.field, d.values) for d in dossier.identity.discrepancies]
    return parts


def _tags(dossier: Dossier) -> list[Text | Table]:
    """One wrapped line per scope and kind, strongest first, with the sources of the line."""
    groups: dict[tuple[str, str], list[Tag]] = {}
    for tag in dossier.tags:
        groups.setdefault((tag.scope.value, tag.kind.value), []).append(tag)

    parts: list[Text | Table] = [_heading("Tags")]
    for (scope, kind), tags in groups.items():
        line = Text(f"{scope.replace('_', ' ')} {kind}s: ", style="bold")
        ordered = sorted(tags, key=lambda tag: -(tag.weight or 0.0))
        line.append(", ".join(tag.name for tag in ordered), style="not bold")
        line.append(" — ")
        line.append_text(_sources(source for tag in ordered for source in tag.sources))
        parts.append(line)
    return parts


def _credits(dossier: Dossier) -> list[Text | Table]:
    table = _table("role", "name", "detail", "sources")
    for credit in dossier.credits:
        table.add_row(credit.role, credit.name, credit.detail or "", _sources(credit.sources))
    return [_heading("Credits"), table]


def _texts(dossier: Dossier) -> list[Text | Table]:
    parts: list[Text | Table] = [_heading("Texts")]
    for text in dossier.texts:
        header = Text(text.kind.value, style="bold")
        details = [text.title, text.publication, text.author, text.date]
        if text.rating is not None and (text.rating.text or text.rating.value is not None):
            scale = f"/{text.rating.scale:g}" if text.rating.scale else ""
            value = f"{text.rating.value:g}" if text.rating.value is not None else ""
            details.append(f"rating {text.rating.text or value}{scale}")
        header.append(" · " + " · ".join(d for d in details if d) if any(details) else "")
        header.append(" — ")
        header.append_text(_sources(text.sources))
        parts.append(header)
        if text.body.strip():
            body = text.body if len(text.body) <= _TEXT_LIMIT else text.body[:_TEXT_LIMIT] + "…"
            parts.append(Text(body))
    return parts


def _relation_line(relation: Relation) -> Text:
    target = relation.target
    line = Text("  ")
    line.append(target.name, style=f"link {target.url}" if target.url else "")
    details = [d for d in (target.artist, target.date, relation.note) if d]
    if details:
        line.append(f" ({', '.join(details)})")
    line.append(" — ")
    line.append_text(_sources(relation.sources))
    return line


def _relations(dossier: Dossier) -> list[Text | Table]:
    parts: list[Text | Table] = [_heading("Relations")]
    for kind in RelationKind:
        group = [relation for relation in dossier.relations if relation.kind is kind]
        if group:
            parts.append(Text(kind.value.replace("_", " "), style="bold"))
            parts += [_relation_line(relation) for relation in group]
    return parts


def _number(value: float) -> str:
    return f"{int(value):,}" if value.is_integer() else f"{value:g}"


def _metrics(dossier: Dossier) -> list[Text | Table]:
    table = _table("metric", "value", "scope", "sources")
    for metric in dossier.metrics:
        scale = f"/{_number(metric.scale)}" if metric.scale is not None else ""
        table.add_row(
            metric.kind.value,
            f"{_number(metric.value)}{scale}",
            metric.scope.value.replace("_", " "),
            _sources(metric.sources),
        )
    return [_heading("Metrics"), table]


def _links(dossier: Dossier) -> list[Text | Table]:
    table = _table("service", "target", "url", "sources")
    for link in dossier.links:
        table.add_row(
            link.service,
            link.target.value,
            Text(link.url, style=f"link {link.url}"),
            _sources(link.sources),
        )
    return [_heading("Links"), table]


def _errors(dossier: Dossier) -> list[Text | Table]:
    table = _table("source", "problem", "reason")
    for error in dossier.errors:
        table.add_row(error.source, Text(error.kind.value, style="red"), error.reason)
    return [_heading("Errors"), table]


def pretty_dossier(dossier: Dossier) -> Group:
    """Lay the dossier out as terminal sections; every fact shows its sources."""
    identity = dossier.identity
    if identity.title is not None:
        artist = f"{identity.artist.value} — " if identity.artist is not None else ""
        title = Text(f"{artist}{identity.title.value}", style="bold")
    else:
        title = Text("Nothing matched the query", style="bold red")

    parts: list[Text | Table] = [title]
    if dossier.found:
        parts += _identity(dossier)

    sections = (
        (dossier.tags, _tags),
        (dossier.credits, _credits),
        (dossier.texts, _texts),
        (dossier.relations, _relations),
        (dossier.metrics, _metrics),
        (dossier.links, _links),
        (dossier.errors, _errors),
    )
    for items, section in sections:
        if items:
            parts += section(dossier)
    return Group(*parts)


def print_dossier(dossier: Dossier, output: OutputFormat, console: Console | None = None) -> None:
    """Print a dossier as rich text, JSON, or Markdown."""
    console = console or Console()
    if output is OutputFormat.JSON:
        console.out(dossier.model_dump_json(indent=2), highlight=False)
    elif output is OutputFormat.MARKDOWN:
        console.out(to_markdown(dossier), highlight=False)
    else:
        console.print(pretty_dossier(dossier))


def _status(info: SourceInfo) -> Text:
    status = info.status
    if status.state is SourceState.READY:
        if status.detail and info.requires:
            wanted = ", ".join(f"{env_variable(r.setting)} for {r.purpose}" for r in info.requires)
            return Text(f"ready; set {wanted}", style="green")
        return Text("ready", style="green")
    if status.state is SourceState.MISSING_CREDENTIAL and info.requires:
        names = ", ".join(env_variable(r.setting) for r in info.requires)
        return Text(f"missing {names}", style="yellow")
    detail = f": {status.detail}" if status.detail else ""
    return Text(f"{status.state.value.replace('_', ' ')}{detail}", style="yellow")


def _default(info: SourceInfo) -> str:
    return "yes" if info.default else ""


def _capabilities(info: SourceInfo) -> str:
    return ", ".join(capability.value for capability in info.capabilities)


def print_sources(
    infos: Sequence[SourceInfo],
    output: OutputFormat,
    console: Console | None = None,
) -> None:
    """Print the sources with their group, default membership, pass, capabilities, and status."""
    console = console or Console()
    if output is OutputFormat.JSON:
        payload = [info.model_dump(mode="json") for info in infos]
        console.out(json.dumps(payload, indent=2), highlight=False)
        return

    if output is OutputFormat.MARKDOWN:
        lines = [
            "| Source | Group | Default | Pass | Contributes | Status |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for info in infos:
            cells = (
                info.source,
                info.group.value,
                _default(info),
                info.pass_.value,
                _capabilities(info),
                _status(info).plain,
            )
            lines.append(f"| {' | '.join(cells)} |")
        console.out("\n".join(lines), highlight=False)
        return

    table = _table("source", "group", "default", "pass", "contributes", "status")
    for info in infos:
        table.add_row(
            info.source,
            info.group.value,
            _default(info),
            info.pass_.value,
            _capabilities(info),
            _status(info),
        )
    console.print(table)


def _outcome_style(outcome: str) -> str:
    return {"ok": "green", "nothing_matched": "yellow"}.get(outcome, "red")


def _problems(record: RunRecord) -> str:
    return ", ".join(f"{s}:{status}" for s, status in record.sources.items() if status != "ok")


def _run_row(record: RunRecord) -> tuple[str, str, str, str, str, str, str]:
    query = record.query or " ".join(record.argv)
    return (
        record.run_id,
        f"{record.started_at:%Y-%m-%d %H:%M}",
        record.command,
        query,
        record.outcome.value,
        _problems(record),
        f"{record.duration_ms / 1000:.1f}",
    )


def print_runs(
    records: Sequence[RunRecord],
    output: OutputFormat,
    root: Path,
    console: Console | None = None,
) -> None:
    """Print journaled runs with their outcome and the sources that did not answer 'ok'."""
    console = console or Console()
    if output is OutputFormat.JSON:
        payload = [record.model_dump(mode="json") for record in records]
        console.out(json.dumps(payload, indent=2, ensure_ascii=False), highlight=False)
        return
    if not records:
        console.print(f"No runs journaled in {root}.")
        return

    columns = ("run", "started (UTC)", "command", "query", "outcome", "problems", "seconds")
    if output is OutputFormat.MARKDOWN:
        lines = [f"| {' | '.join(columns)} |", f"|{' --- |' * len(columns)}"]
        lines += [f"| {' | '.join(_run_row(record))} |" for record in records]
        console.out("\n".join(lines), highlight=False)
        return

    table = _table(*columns)
    for index in (0, 1, 4, 6):
        table.columns[index].no_wrap = True
    for record in records:
        *cells, outcome, problems, seconds = _run_row(record)
        table.add_row(
            *cells,
            Text(outcome, style=_outcome_style(outcome)),
            Text(problems, style="yellow"),
            seconds,
        )
    console.print(table)


def _field(event: object, *path: str) -> object:
    value: object = event
    for key in path:
        value = value.get(key) if isinstance(value, Mapping) else None
    return value


def _items(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _key(value: object) -> str:
    """Describe a record key or candidate of a trace event."""
    artist, title = _field(value, "artist"), _field(value, "title")
    version = _field(value, "version")
    described = f"{artist} - {title}"
    if isinstance(version, str) and version != "original":
        described += f" [{version}]"
    return described


def _score(value: object) -> str:
    return f"{value:.2f}" if isinstance(value, float | int) else "?"


def _seconds(milliseconds: object) -> str:
    return f"{milliseconds / 1000:.2f} s" if isinstance(milliseconds, int | float) else "? s"


def _run_start(event: Mapping[str, object]) -> Text:
    argv = " ".join(str(arg) for arg in _items(event.get("argv")))
    return Text.assemble(
        ("deadwax ", "bold"),
        (argv, "bold"),
        (f"  deadwax {event.get('version')}, Python {event.get('python')}", "dim"),
    )


def _query(event: Mapping[str, object]) -> Text:
    query = event.get("query")
    target = _field(query, "url") or f"{_field(query, 'artist')} - {_field(query, 'title')}"
    return Text(f"query: {target} ({_field(query, 'kind') or 'kind unknown'})")


def _selected(event: Mapping[str, object]) -> Text:
    ready = ", ".join(str(name) for name in _items(event.get("ready")))
    text = Text(f"sources: {ready}")
    skipped = event.get("skipped")
    if isinstance(skipped, Mapping) and skipped:
        reasons = "; ".join(f"{source} ({reason})" for source, reason in skipped.items())
        text.append(f"\nskipped: {reasons}", style="yellow")
    return text


def _pass(event: Mapping[str, object]) -> Text:
    sources = ", ".join(str(name) for name in _items(event.get("sources")))
    text = Text(f"\npass {event.get('pass')}: {sources}", style="bold underline")
    identity = event.get("identity")
    if _field(identity, "title") is not None:
        text.append(f"\n  context: {_key(identity)}, {event.get('links')} links", style="dim")
    return text


def _request(event: Mapping[str, object]) -> Text:
    status = event.get("status")
    error = event.get("error")
    result = f"→ {status}" if status is not None else f"→ {_field(error, 'type')}"
    details = [
        f"cache {event.get('cache')}",
        f"{event.get('attempts')} attempts",
        _seconds(event.get("duration_ms")),
    ]
    if isinstance(event.get("bytes"), int):
        details.append(f"{event.get('bytes')} B")
    if error is not None:
        details.append(str(_field(error, "message")))
    style = "" if isinstance(status, int) and status < 400 else "red"  # noqa: PLR2004 -- HTTP
    return Text.assemble(
        f"{event.get('method')} {event.get('url')} ",
        (result, style),
        (f" ({', '.join(details)})", "dim"),
    )


def _compare(event: Mapping[str, object]) -> Text:
    verdict = str(event.get("verdict"))
    failed = ", ".join(str(check) for check in _items(event.get("failed")))
    style = {"match": "green", "other_version": "yellow"}.get(verdict, "red")
    return Text.assemble(
        f"compare {_key(event.get('candidate'))} ",
        (f"→ {verdict}", style),
        (
            f" (artist {_score(event.get('artist_score'))}, "
            f"title {_score(event.get('title_score'))}"
            + (f"; failed {failed}" if failed else "")
            + ")",
            "dim",
        ),
    )


def _retry(event: Mapping[str, object]) -> Text:
    cause = f"HTTP {event['status']}" if "status" in event else str(event.get("error"))
    delay = event.get("delay_s")
    wait = f", waiting {delay:.1f} s" if isinstance(delay, float | int) else ""
    return Text(f"retry {event.get('url')} after {cause}{wait}", style="yellow")


def _challenge(event: Mapping[str, object]) -> Text:
    return Text(
        f"{event.get('challenge')} via {event.get('fetcher')}: {event.get('url')}",
        style="yellow",
    )


def _pick(event: Mapping[str, object]) -> Text:
    hits = len(_items(event.get("hits")) or _items(event.get("matched")))
    picked = event.get("picked")
    query = f" for {event['query']}" if "query" in event else ""
    return Text(f"search{query}: {hits} kept, picked {picked or 'nothing'}")


def _adapter_end(event: Mapping[str, object]) -> Text:
    errors = _items(event.get("errors"))
    duration = _seconds(event.get("duration_ms"))
    if errors:
        first = errors[0]
        url = _field(first, "url")
        return Text.assemble(
            (f"{_field(first, 'kind')}: {_field(first, 'reason')}", "red"),
            (f" ({duration}{', ' + str(url) if url else ''})", "dim"),
        )
    facts = event.get("facts")
    counts = ", ".join(
        f"{count} {name}"
        for name, count in (facts.items() if isinstance(facts, Mapping) else ())
        if count
    )
    candidate = event.get("candidate")
    found = _key(candidate) if candidate is not None else "no candidate"
    return Text.assemble(
        ("ok", "green"),
        f": {found}",
        (f" ({duration}; {counts or 'no facts'})", "dim"),
    )


def _merge_reference(event: Mapping[str, object]) -> Text:
    reference = event.get("reference")
    described = _key(reference) if reference is not None else "the first candidate"
    return Text(f"\nmerge of {event.get('partials')} results against {described}", style="bold")


def _reference(event: Mapping[str, object]) -> Text:
    return Text(f"compared with {event.get('reference')}", style="bold")


def _judge(event: Mapping[str, object]) -> Text:
    verdict = str(event.get("verdict"))
    style = {"match": "green", "other_version": "yellow"}.get(verdict, "red")
    return Text.assemble(
        "merge: ",
        (verdict, style),
        (
            f" (artist {_score(event.get('artist_score'))}, "
            f"title {_score(event.get('title_score'))})",
            "dim",
        ),
    )


def _run_end(event: Mapping[str, object]) -> Text:
    summary = event.get("summary")
    outcome = str(_field(summary, "outcome"))
    text = Text("\n")
    text.append(f"{outcome}", style=f"bold {_outcome_style(outcome)}")
    text.append(f" in {_seconds(_field(summary, 'duration_ms'))}")
    if (identity := _field(summary, "identity")) is not None:
        text.append(f": {identity}")
    for error in _items(_field(summary, "errors")):
        source, kind = _field(error, "source"), _field(error, "kind")
        text.append(f"\n  {source}: {kind} — {_field(error, 'reason')}", style="yellow")
    return text


_EVENT_RENDERERS: dict[str, Callable[[Mapping[str, object]], Text]] = {
    "run.start": _run_start,
    "query.parsed": _query,
    "lookup.selected": _selected,
    "pass.start": _pass,
    "http.request": _request,
    "http.retry": _retry,
    "http.challenge": _challenge,
    "match.compare": _compare,
    "reference": _reference,
    "search.pick": _pick,
    "search.ranked": _pick,
    "adapter.end": _adapter_end,
    "merge.reference": _merge_reference,
    "merge.judge": _judge,
    "run.end": _run_end,
}

# Events that the timeline leaves to --format json.
_QUIET_EVENTS = frozenset({"run.settings"})


def _event_line(event: Mapping[str, object]) -> Text:
    name = str(event.get("event"))
    renderer = _EVENT_RENDERERS.get(name)
    if renderer is not None:
        text = renderer(event)
    else:
        fields = {
            key: value
            for key, value in event.items()
            if key not in {"event", "level", "logger", "timestamp", "run_id", "source", "pass"}
        }
        logger = event.get("logger")
        if isinstance(logger, str) and not logger.startswith("deadwax"):
            fields = {"logger": logger, **fields}
        text = Text(name, style="yellow" if event.get("level") in {"warning", "error"} else "")
        if fields:
            text.append(f" {json.dumps(fields, ensure_ascii=False, default=str)}", style="dim")
        if isinstance(exception := event.get("exception"), str):
            text = Text(f"{name}\n{exception}", style="red")
    source = event.get("source")
    if isinstance(source, str) and name not in {"pass.start", "lookup.selected"}:
        return Text.assemble("  ", (f"[{source}] ", "cyan"), text)
    return text


def print_run(
    events: Sequence[Mapping[str, object]],
    output: OutputFormat,
    console: Console | None = None,
    *,
    full: bool = False,
) -> None:
    """Print one run's events as a timeline; JSON prints them as recorded."""
    console = console or Console()
    if output is OutputFormat.JSON:
        console.out(json.dumps(list(events), indent=2, ensure_ascii=False), highlight=False)
        return

    shown = [event for event in events if event.get("event") not in _QUIET_EVENTS]
    if not full:
        # merge.judge repeats the scores of the final merge's comparisons.
        shown = [
            event
            for event in shown
            if event.get("stage") != "context"
            and not (event.get("stage") == "final" and event.get("event") == "match.compare")
        ]
    lines: list[Text] = []
    references: dict[object, str] = {}
    for event in shown:
        if event.get("event") == "match.compare":
            source, reference = event.get("source"), _key(event.get("reference"))
            if references.get(source) != reference:
                references[source] = reference
                lines.append(_event_line({**event, "event": "reference", "reference": reference}))
        lines.append(_event_line(event))
    if output is OutputFormat.MARKDOWN:
        body = "\n".join(line.plain for line in lines)
        console.out(f"```\n{body}\n```", highlight=False)
        return
    console.print(Group(*lines))
