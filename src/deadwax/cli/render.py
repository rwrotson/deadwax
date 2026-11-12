import json
from collections.abc import Iterable, Sequence
from enum import StrEnum

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


def print_sources(
    infos: Sequence[SourceInfo], output: OutputFormat, console: Console | None = None
) -> None:
    """Print the sources with their pass, capabilities, and status."""
    console = console or Console()
    if output is OutputFormat.JSON:
        payload = [info.model_dump(mode="json") for info in infos]
        console.out(json.dumps(payload, indent=2), highlight=False)
        return
    if output is OutputFormat.MARKDOWN:
        lines = ["| Source | Pass | Contributes | Status |", "| --- | --- | --- | --- |"]
        for info in infos:
            capabilities = ", ".join(capability.value for capability in info.capabilities)
            row = f"| {info.source} | {info.pass_.value} | {capabilities} | {_status(info).plain} |"
            lines.append(row)
        console.out("\n".join(lines), highlight=False)
        return
    table = _table("source", "pass", "contributes", "status")
    for info in infos:
        capabilities = ", ".join(capability.value for capability in info.capabilities)
        table.add_row(info.source, info.pass_.value, capabilities, _status(info))
    console.print(table)
