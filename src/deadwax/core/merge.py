import logging
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from deadwax.core.matching import RecordKey, Verdict, compare
from deadwax.core.models import (
    AdapterError,
    Attributed,
    Credit,
    Discrepancy,
    Dossier,
    Entity,
    EntityType,
    ErrorKind,
    ExternalId,
    Fact,
    Identity,
    LabelRef,
    Link,
    LinkTarget,
    Metric,
    Partial,
    Provenance,
    RecordCandidate,
    Relation,
    RelationKind,
    Scope,
    Sourced,
    Tag,
    Text,
    TextKind,
    VersionInfo,
)
from deadwax.core.normalize import (
    normalize_artist,
    normalize_barcode,
    normalize_code,
    normalize_text,
)
from deadwax.core.query import EntityKind, Query
from deadwax.core.versions import parse_title

logger = logging.getLogger(__name__)

QUERY_SOURCE = "query"

_SCOPE_ORDER = {
    EntityKind.TRACK: (
        Scope.RECORDING,
        Scope.WORK,
        Scope.RELEASE,
        Scope.RELEASE_GROUP,
        Scope.ARTIST,
        Scope.LABEL,
    ),
    EntityKind.ALBUM: (
        Scope.RELEASE_GROUP,
        Scope.RELEASE,
        Scope.RECORDING,
        Scope.WORK,
        Scope.ARTIST,
        Scope.LABEL,
    ),
}
_LINK_ORDER = {
    EntityKind.TRACK: (
        LinkTarget.TRACK,
        LinkTarget.ALBUM,
        LinkTarget.ARTIST,
        LinkTarget.LABEL,
        LinkTarget.OTHER,
    ),
    EntityKind.ALBUM: (
        LinkTarget.ALBUM,
        LinkTarget.TRACK,
        LinkTarget.ARTIST,
        LinkTarget.LABEL,
        LinkTarget.OTHER,
    ),
}
_TEXT_ORDER = tuple(TextKind)
_RELATION_ORDER = tuple(RelationKind)


@dataclass(slots=True)
class _Judgement:
    accepted: list[Partial] = field(default_factory=list)
    other_versions: list[Partial] = field(default_factory=list)
    errors: list[AdapterError] = field(default_factory=list)


def _candidate_key(candidate: RecordCandidate, kind: EntityKind | None = None) -> RecordKey:
    return RecordKey(
        artist=candidate.artist,
        title=candidate.title,
        kind=candidate.kind or kind,
        version=candidate.version,
    )


def _reference(query: Query, partials: Sequence[Partial]) -> RecordKey | None:
    """Use the query text, or for a URL query the first candidate (the URL's own page)."""
    if query.artist and query.title:
        return RecordKey(artist=query.artist, title=query.title, kind=query.kind)
    for partial in partials:
        if partial.candidate is not None:
            return _candidate_key(partial.candidate, query.kind)
    return None


def _provenance(partial: Partial) -> Provenance:
    url = partial.candidate.url if partial.candidate is not None else None
    return Provenance(source=partial.source, url=url)


def _judge(reference: RecordKey | None, partials: Iterable[Partial]) -> _Judgement:
    judgement = _Judgement()
    for partial in partials:
        judgement.errors.extend(partial.errors)
        candidate = partial.candidate
        if candidate is None or reference is None:
            judgement.accepted.append(partial)
            continue
        verdict = compare(reference, _candidate_key(candidate)).verdict
        if verdict is Verdict.MATCH:
            judgement.accepted.append(partial)
        elif verdict is Verdict.OTHER_VERSION:
            judgement.other_versions.append(partial)
        else:
            logger.debug("%s candidate %r does not match", partial.source, candidate)
            judgement.errors.append(
                AdapterError(
                    source=partial.source,
                    kind=ErrorKind.NO_MATCH,
                    reason=f"best candidate '{candidate.artist} - {candidate.title}' "
                    "does not match the query",
                    url=candidate.url,
                ),
            )

    return judgement


def _union(*groups: Iterable[Provenance]) -> list[Provenance]:
    return list(dict.fromkeys(provenance for group in groups for provenance in group))


def _first(values: list[str]) -> str:
    return values[0]


def _most_precise(values: list[str]) -> str:
    return max(values, key=len)


def _consensus(
    name: str,
    observations: Iterable[tuple[str, str, Provenance]],
    pick: Callable[[list[str]], str] = _first,
) -> tuple[Sourced[str] | None, Discrepancy | None]:
    """Group observed values by key; the best-supported group wins, several groups disagree."""
    groups: dict[str, list[tuple[str, Provenance]]] = {}
    for value, key, provenance in observations:
        groups.setdefault(key, []).append((value, provenance))
    options = [
        Sourced(value=pick([value for value, _ in items]), sources=_union(p for _, p in items))
        for items in groups.values()
    ]
    if not options:
        return None, None
    winner = max(options, key=lambda option: len(option.sources))
    return winner, Discrepancy(field=name, values=options) if len(options) > 1 else None


def _version_label(version: VersionInfo) -> str:
    return str(version.kind) if version.detail is None else f"{version.kind}: {version.detail}"


def _resolve_version(candidate: RecordCandidate) -> VersionInfo:
    return candidate.version or parse_title(candidate.title).version


def _version(accepted: list[RecordCandidate]) -> VersionInfo:
    versions = [_resolve_version(candidate) for candidate in accepted]
    detailed = [version for version in versions if version.detail is not None]
    return (detailed or versions or [VersionInfo()])[0]


def _version_discrepancy(
    version: VersionInfo,
    title: Sourced[str] | None,
    other_versions: list[Partial],
) -> Discrepancy | None:
    others = [
        (_version_label(_resolve_version(partial.candidate)), _provenance(partial))
        for partial in other_versions
        if partial.candidate is not None
    ]
    if not others:
        return None

    sources = title.sources if title is not None else [Provenance(source=QUERY_SOURCE)]
    label = _version_label(version)
    observations = [(label, label, source) for source in sources]
    observations += [(other, other, provenance) for other, provenance in others]
    return _consensus("version", observations)[1]


def _labels(matched: list[tuple[RecordCandidate, Provenance]]) -> list[LabelRef]:
    labels: dict[tuple[str, str], LabelRef] = {}
    for candidate, provenance in matched:
        for label in candidate.labels:
            key = (normalize_text(label.name), normalize_code(label.catalog_number or ""))
            known = labels.get(key)
            labels[key] = LabelRef(
                name=known.name if known else label.name,
                catalog_number=known.catalog_number if known else label.catalog_number,
                sources=_union(known.sources if known else [], [provenance]),
            )
    return list(labels.values())


def _codes(
    matched: list[tuple[RecordCandidate, Provenance]],
    values: Callable[[RecordCandidate], list[str]],
    key: Callable[[str], str],
) -> list[Sourced[str]]:
    groups: dict[str, Sourced[str]] = {}
    for candidate, provenance in matched:
        for value in values(candidate):
            code = key(value)
            known = groups.get(code)
            groups[code] = Sourced(
                value=known.value if known else value,
                sources=_union(known.sources if known else [], [provenance]),
            )
    return list(groups.values())


def _external_ids(
    matched: list[tuple[RecordCandidate, Provenance]],
) -> tuple[list[ExternalId], list[Discrepancy]]:
    ids: dict[tuple[str, str], ExternalId] = {}
    for candidate, provenance in matched:
        for kind, value in candidate.ids.items():
            known = ids.get((kind, value))
            ids[kind, value] = ExternalId(
                kind=kind,
                value=value,
                sources=_union(known.sources if known else [], [provenance]),
            )

    discrepancies = []
    for kind in dict.fromkeys(external_id.kind for external_id in ids.values()):
        values = [
            Sourced(value=external_id.value, sources=external_id.sources)
            for external_id in ids.values()
            if external_id.kind == kind
        ]
        if len(values) > 1:
            discrepancies.append(Discrepancy(field=f"ids.{kind}", values=values))
    return list(ids.values()), discrepancies


def build_identity(
    query: Query,
    accepted: list[Partial],
    other_versions: list[Partial],
) -> Identity:
    """Combine the candidates of matching partials into one identity with its discrepancies."""
    matched = [
        (partial.candidate, _provenance(partial))
        for partial in accepted
        if partial.candidate is not None
    ]

    artist, artist_conflict = _consensus(
        "artist",
        ((c.artist, normalize_artist(c.artist), p) for c, p in matched),
    )
    title, title_conflict = _consensus(
        "title",
        (
            (c.title, f"{normalize_text(parse_title(c.title).base)}|{_resolve_version(c).kind}", p)
            for c, p in matched
        ),
    )
    date, date_conflict = _consensus(
        "date",
        ((c.date, c.date[:4], p) for c, p in matched if c.date),
        _most_precise,
    )

    version = _version([candidate for candidate, _ in matched])
    version_conflict = _version_discrepancy(version, title, other_versions)
    external_ids, id_conflicts = _external_ids(matched)
    conflicts = [artist_conflict, title_conflict, version_conflict, date_conflict, *id_conflicts]
    kinds = [candidate.kind for candidate, _ in matched if candidate.kind is not None]

    return Identity(
        kind=query.kind or (kinds[0] if kinds else None),
        artist=artist,
        title=title,
        version=version,
        date=date,
        labels=_labels(matched),
        isrcs=_codes(matched, lambda c: c.isrcs, normalize_code),
        upcs=_codes(matched, lambda c: c.upcs, normalize_barcode),
        external_ids=external_ids,
        discrepancies=[conflict for conflict in conflicts if conflict is not None],
    )


def _combine[T: Attributed](kept: T, other: T) -> T:
    return kept.model_copy(update={"sources": _union(kept.sources, other.sources)})


def _combine_tags(kept: Tag, other: Tag) -> Tag:
    weights = [weight for weight in (kept.weight, other.weight) if weight is not None]
    return _combine(kept, other).model_copy(update={"weight": max(weights, default=None)})


def _combine_relations(kept: Relation, other: Relation) -> Relation:
    """Union the sources and fill what the kept target lacks from the other one."""
    target = kept.target.model_copy(
        update={
            "artist": kept.target.artist or other.target.artist,
            "date": kept.target.date or other.target.date,
            "url": kept.target.url or other.target.url,
            "ids": other.target.ids | kept.target.ids,
        },
    )
    return _combine(kept, other).model_copy(update={"target": target})


# Targets that are events: the same name on another date is another entity.
_DATED_TARGETS = frozenset({EntityType.BROADCAST, EntityType.MIX})


def _relation_key(relation: Relation) -> Hashable:
    target = relation.target
    return (
        relation.kind,
        target.type,
        normalize_artist(target.artist or ""),
        normalize_text(target.name),
        target.date if target.type in _DATED_TARGETS else None,
    )


def _metric_key(metric: Metric) -> Hashable:
    """Counts of different sources measure different audiences and are never combined."""
    return (metric.kind, metric.scope, tuple(provenance.source for provenance in metric.sources))


def _dedupe[T: Attributed](
    items: Iterable[T],
    key: Callable[[T], Hashable],
    combine: Callable[[T, T], T] = _combine,
) -> list[T]:
    merged: dict[Hashable, T] = {}
    for item in items:
        item_key = key(item)
        merged[item_key] = combine(merged[item_key], item) if item_key in merged else item
    return list(merged.values())


def _url_key(url: str) -> str:
    scheme, _, rest = url.partition("://")
    host, slash, path = rest.partition("/")
    return f"{scheme.lower()}://{host.lower().removeprefix('www.')}{slash}{path}".rstrip("/")


def _other_version_relation(partial: Partial, candidate: RecordCandidate) -> Relation:
    is_album = candidate.kind is EntityKind.ALBUM
    return Relation(
        kind=RelationKind.OTHER_VERSION,
        scope=Scope.RELEASE if is_album else Scope.RECORDING,
        target=Entity(
            type=EntityType.RELEASE if is_album else EntityType.RECORDING,
            name=candidate.title,
            artist=candidate.artist,
            date=candidate.date,
            url=candidate.url,
            ids=candidate.ids,
        ),
        note=_version_label(_resolve_version(candidate)),
        sources=[_provenance(partial)],
    )


def _scope_rank(kind: EntityKind) -> Callable[[Fact], int]:
    order = _SCOPE_ORDER[kind]
    return lambda fact: order.index(fact.scope)


@dataclass(frozen=True, slots=True)
class _Facts:
    tags: list[Tag]
    credits: list[Credit]
    texts: list[Text]
    relations: list[Relation]
    metrics: list[Metric]
    links: list[Link]


def _text_key(text: Text) -> tuple[object, ...]:
    """Texts are the same by body; scores without a body by publication, rating, and title."""
    if text.body.strip():
        return (text.kind, normalize_text(text.body))
    publication = normalize_text(text.publication or "")
    return (text.kind, "", publication, text.rating, normalize_text(text.title or ""))


def _facts(kind: EntityKind, accepted: list[Partial], other_versions: list[Partial]) -> _Facts:
    scope_rank = _scope_rank(kind)

    tags = _dedupe(
        (tag for p in accepted for tag in p.tags),
        lambda t: normalize_text(t.name),
        _combine_tags,
    )

    credit_facts = _dedupe(
        (credit for p in accepted for credit in p.credits),
        lambda c: (
            normalize_text(c.role),
            normalize_artist(c.name),
            normalize_text(c.detail or ""),
        ),
    )

    texts = _dedupe((text for p in accepted for text in p.texts), _text_key)

    found_relations = (relation for p in accepted for relation in p.relations)
    version_relations = (
        _other_version_relation(p, p.candidate) for p in other_versions if p.candidate is not None
    )
    relations = _dedupe((*found_relations, *version_relations), _relation_key, _combine_relations)
    metrics = _dedupe((metric for p in accepted for metric in p.metrics), _metric_key)

    links = _dedupe((link for p in accepted for link in p.links), lambda link: _url_key(link.url))
    link_order = _LINK_ORDER[kind]
    return _Facts(
        tags=sorted(tags, key=lambda t: (scope_rank(t), -len(t.sources), -(t.weight or 0.0))),
        credits=sorted(credit_facts, key=scope_rank),
        texts=sorted(texts, key=lambda t: (scope_rank(t), _TEXT_ORDER.index(t.kind))),
        relations=sorted(relations, key=lambda r: (_RELATION_ORDER.index(r.kind), scope_rank(r))),
        metrics=sorted(metrics, key=scope_rank),
        links=sorted(links, key=lambda link: link_order.index(link.target)),
    )


def merge(
    query: Query,
    partials: Sequence[Partial],
    errors: Iterable[AdapterError] = (),
    *,
    generated_at: datetime,
) -> Dossier:
    """Build a dossier from adapter results, keeping only facts about the queried version."""
    judgement = _judge(_reference(query, partials), partials)
    identity = build_identity(query, judgement.accepted, judgement.other_versions)
    facts = _facts(identity.kind or EntityKind.TRACK, judgement.accepted, judgement.other_versions)
    return Dossier(
        query=query,
        identity=identity,
        tags=facts.tags,
        credits=facts.credits,
        texts=facts.texts,
        relations=facts.relations,
        metrics=facts.metrics,
        links=facts.links,
        errors=[*errors, *judgement.errors],
        generated_at=generated_at,
    )
