from collections.abc import Callable, Iterable

from deadwax.core.models import (
    AdapterError,
    Credit,
    Dossier,
    Identity,
    Link,
    Metric,
    Provenance,
    Relation,
    ReviewLink,
    Sourced,
    Tag,
    Text,
    VersionKind,
)


def _sources(sources: Iterable[Provenance]) -> str:
    return ", ".join(
        f"[{source.source}]({source.url})" if source.url else source.source for source in sources
    )


def _sourced(label: str, value: Sourced[str] | None) -> list[str]:
    return [] if value is None else [f"- **{label}:** {value.value} ({_sources(value.sources)})"]


def _heading(identity: Identity, fallback: str) -> str:
    if identity.artist is None or identity.title is None:
        return f"# {fallback}"
    return f"# {identity.artist.value} — {identity.title.value}"


def _identity(identity: Identity) -> list[str]:
    lines = ["## Identity", ""]
    if identity.kind is not None:
        lines.append(f"- **Kind:** {identity.kind}")
    lines += _sourced("Artist", identity.artist) + _sourced("Title", identity.title)
    if identity.version.kind is not VersionKind.ORIGINAL or identity.version.detail:
        detail = f" ({identity.version.detail})" if identity.version.detail else ""
        lines.append(f"- **Version:** {identity.version.kind}{detail}")
    lines += _sourced("Date", identity.date)
    if identity.bpm is not None:
        lines.append(f"- **BPM:** {identity.bpm.value:g} ({_sources(identity.bpm.sources)})")
    lines += _sourced("Key", identity.key)

    lines += [
        f"- **Label:** {label.name}"
        + (f", {label.catalog_number}" if label.catalog_number else "")
        + f" ({_sources(label.sources)})"
        for label in identity.labels
    ]
    lines += [f"- **ISRC:** {isrc.value} ({_sources(isrc.sources)})" for isrc in identity.isrcs]
    lines += [f"- **UPC:** {upc.value} ({_sources(upc.sources)})" for upc in identity.upcs]
    lines += [
        f"- **Copyright:** {line.value} ({_sources(line.sources)})" for line in identity.copyrights
    ]
    lines += [
        f"- **{item.kind}:** {item.value} ({_sources(item.sources)})"
        for item in identity.external_ids
    ]

    for discrepancy in identity.discrepancies:
        values = "; ".join(
            f"{value.value} ({_sources(value.sources)})" for value in discrepancy.values
        )
        lines.append(f"- **Sources disagree on {discrepancy.field}:** {values}")
    return lines


def _section[T](title: str, items: list[T], render: Callable[[T], list[str]]) -> list[str]:
    if not items:
        return []
    return ["", f"## {title}", "", *(line for item in items for line in render(item))]


def _tag(tag: Tag) -> list[str]:
    weight = f", {tag.weight:.2f}" if tag.weight is not None else ""
    return [f"- {tag.name} ({tag.kind}, {tag.scope}{weight}) — {_sources(tag.sources)}"]


def _credit(credit: Credit) -> list[str]:
    detail = f" ({credit.detail})" if credit.detail else ""
    return [f"- {credit.role}: {credit.name}{detail} — {_sources(credit.sources)}"]


def _text(text: Text) -> list[str]:
    if not text.body.strip():
        return _score(text)
    byline = ", ".join(part for part in (text.publication, text.author, text.date) if part)
    rating = _rating(text)
    rating = f" — {rating}" if rating else ""
    heading = f"### {text.title or text.kind.capitalize()}"
    meta = f"*{text.kind}, {text.scope}{', ' + byline if byline else ''}{rating}*"
    quoted = [f"> {line}" if line else ">" for line in text.body.splitlines()]
    return [heading, "", meta, "", *quoted, "", f"Source: {_sources(text.sources)}", ""]


def _score(text: Text) -> list[str]:
    """A score without a review body, as one list line."""
    name = text.publication or text.author or text.kind.capitalize()
    rating = _rating(text)
    details = ", ".join(d for d in (text.title, str(text.scope), text.language) if d)
    line = f"- {name}{': ' + rating if rating else ''} ({details}) — {_sources(text.sources)}"
    return [line, ""]


def _rating(text: Text) -> str:
    if text.rating is None:
        return ""
    if text.rating.text:
        return text.rating.text
    if text.rating.value is None:
        return ""
    scale = f"/{text.rating.scale:g}" if text.rating.scale is not None else ""
    return f"{text.rating.value:g}{scale}"


def _relation(relation: Relation) -> list[str]:
    target = relation.target
    name = f"{target.artist} — {target.name}" if target.artist else target.name
    name = f"[{name}]({target.url})" if target.url else name
    note = f" ({relation.note})" if relation.note else ""
    return [f"- {relation.kind}: {name}{note} — {_sources(relation.sources)}"]


def _number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"


def _metric(metric: Metric) -> list[str]:
    value = _number(metric.value)
    scale = f"/{_number(metric.scale)}" if metric.scale is not None else ""
    return [f"- {metric.kind}: {value}{scale} ({metric.scope}) — {_sources(metric.sources)}"]


def _link(link: Link) -> list[str]:
    return [f"- {link.service} ({link.target}): {link.url} — {_sources(link.sources)}"]


def _review_link(link: ReviewLink) -> list[str]:
    return [f"- {link.publication or 'Review'}: {link.url} — {_sources(link.sources)}"]


def _error(error: AdapterError) -> list[str]:
    return [f"- {error.source}: {error.kind} — {error.reason}"]


def to_markdown(dossier: Dossier) -> str:
    """Render a dossier as Markdown with the source of every fact."""
    fallback = dossier.query.url or f"{dossier.query.artist} - {dossier.query.title}"
    lines = [
        _heading(dossier.identity, fallback),
        "",
        *_identity(dossier.identity),
        *_section("Tags", dossier.tags, _tag),
        *_section("Credits", dossier.credits, _credit),
        *_section("Texts", dossier.texts, _text),
        *_section("Relations", dossier.relations, _relation),
        *_section("Metrics", dossier.metrics, _metric),
        *_section("Links", dossier.links, _link),
        *_section("Review links", dossier.review_links, _review_link),
        *_section("Errors", dossier.errors, _error),
    ]
    return "\n".join(lines).rstrip() + "\n"
