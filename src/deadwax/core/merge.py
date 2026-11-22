import logging
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from deadwax.core.events import TraceEvent, trace, trace_scope
from deadwax.core.matching import NameKey, RecordKey, Verdict, compare, compare_names
from deadwax.core.models import (
    AdapterError,
    ArtistCandidate,
    ArtistIdentity,
    ArtistType,
    Attributed,
    Candidate,
    Discrepancy,
    Dossier,
    Entity,
    EntityType,
    ErrorKind,
    ExternalId,
    Fact,
    Facts,
    Identity,
    LabelCandidate,
    LabelIdentity,
    LabelRef,
    Link,
    LinkTarget,
    Metric,
    Partial,
    Provenance,
    RecordCandidate,
    RecordIdentity,
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
    normalize_copyright,
    normalize_key,
    normalize_text,
    shingle_overlap,
    strip_ellipsis,
)
from deadwax.core.query import (
    AlbumQuery,
    ArtistQuery,
    EntityKind,
    LabelQuery,
    Query,
    TrackQuery,
    normalize_code,
)
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
    EntityKind.ARTIST: (
        Scope.ARTIST,
        Scope.LABEL,
        Scope.RELEASE_GROUP,
        Scope.RELEASE,
        Scope.RECORDING,
        Scope.WORK,
    ),
    EntityKind.LABEL: (
        Scope.LABEL,
        Scope.ARTIST,
        Scope.RELEASE_GROUP,
        Scope.RELEASE,
        Scope.RECORDING,
        Scope.WORK,
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
    EntityKind.ARTIST: (
        LinkTarget.ARTIST,
        LinkTarget.LABEL,
        LinkTarget.ALBUM,
        LinkTarget.TRACK,
        LinkTarget.OTHER,
    ),
    EntityKind.LABEL: (
        LinkTarget.LABEL,
        LinkTarget.ARTIST,
        LinkTarget.ALBUM,
        LinkTarget.TRACK,
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


type _Key = RecordKey | NameKey


def _candidate_key(candidate: Candidate, kind: EntityKind | None = None) -> _Key:
    if isinstance(candidate, RecordCandidate):
        return RecordKey(
            artist=candidate.artist,
            title=candidate.title,
            kind=candidate.kind or kind,
            version=candidate.version,
        )
    return NameKey(name=candidate.name, kind=candidate.kind, ids=candidate.ids)


def _describe(candidate: Candidate) -> str:
    if isinstance(candidate, RecordCandidate):
        return f"{candidate.artist} - {candidate.title}"
    return candidate.name


def _reference(query: Query, partials: Sequence[Partial]) -> _Key | None:
    """Use the query text with established name IDs, or the URL's first candidate."""
    match query:
        case (
            TrackQuery(artist=str(artist), title=str(title))
            | AlbumQuery(
                artist=str(artist),
                title=str(title),
            )
        ):
            return RecordKey(artist=artist, title=title, kind=query.kind)
        case ArtistQuery(name=str(name)) | LabelQuery(name=str(name)):
            reference = NameKey(name=name, kind=query.kind, ids=query.ids)
            for partial in partials:
                candidate = partial.candidate
                if isinstance(candidate, ArtistCandidate | LabelCandidate) and candidate.ids:
                    key = NameKey(name=candidate.name, kind=candidate.kind, ids=candidate.ids)
                    if compare_names(reference, key).verdict is Verdict.MATCH:
                        return NameKey(name=name, kind=query.kind, ids=candidate.ids | query.ids)
            return reference
    for partial in partials:
        if partial.candidate is not None:
            return _candidate_key(partial.candidate, query.kind)
    return None


def _compare(reference: _Key, candidate: _Key) -> tuple[Verdict, dict[str, float]]:
    """Compare keys of one family; a record and a name never match."""
    if isinstance(reference, RecordKey) and isinstance(candidate, RecordKey):
        match = compare(reference, candidate)
        scores = {"artist_score": match.artist_score, "title_score": match.title_score}
        return match.verdict, scores
    if isinstance(reference, NameKey) and isinstance(candidate, NameKey):
        name_match = compare_names(reference, candidate)
        return name_match.verdict, {"name_score": name_match.name_score}
    return Verdict.NO_MATCH, {}


def _provenance(partial: Partial) -> Provenance:
    url = partial.candidate.url if partial.candidate is not None else None
    return Provenance(source=partial.source, url=url)


def _judge(reference: _Key | None, partials: Iterable[Partial]) -> _Judgement:
    judgement = _Judgement()
    for partial in partials:
        judgement.errors.extend(partial.errors)
        candidate = partial.candidate
        if candidate is None or reference is None:
            judgement.accepted.append(partial)
            continue
        with trace_scope(source=partial.source):
            verdict, scores = _compare(reference, _candidate_key(candidate))
            trace(
                logger,
                TraceEvent.MERGE_JUDGE,
                verdict=verdict,
                **{name: round(score, 3) for name, score in scores.items()},
                candidate_url=candidate.url,
            )
        if verdict is Verdict.MATCH:
            judgement.accepted.append(partial)
        elif verdict is Verdict.OTHER_VERSION:
            judgement.other_versions.append(partial)
        else:
            judgement.errors.append(
                AdapterError(
                    source=partial.source,
                    kind=ErrorKind.NO_MATCH,
                    reason=f"best candidate '{_describe(candidate)}' does not match the query",
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


def _format_bpm(bpm: float) -> str:
    return f"{bpm:g}"


def _bpm(
    matched: list[tuple[RecordCandidate, Provenance]],
) -> tuple[Sourced[float] | None, Discrepancy | None]:
    """Tempos agree when they round to the same whole beat."""
    agreed, conflict = _consensus(
        "bpm",
        ((_format_bpm(c.bpm), str(round(c.bpm)), p) for c, p in matched if c.bpm is not None),
    )
    if agreed is None:
        return None, conflict
    return Sourced(value=float(agreed.value), sources=agreed.sources), conflict


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
        if isinstance(partial.candidate, RecordCandidate)
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
    matched: Sequence[tuple[Candidate, Provenance]],
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
    candidates = [partial.candidate for partial in accepted if partial.candidate is not None]
    kind = query.kind or next((c.kind for c in candidates if c.kind is not None), None)
    match kind:
        case EntityKind.ARTIST:
            return _artist_identity(accepted)
        case EntityKind.LABEL:
            return _label_identity(accepted)
        case _:
            return _record_identity(kind, accepted, other_versions)


def _record_identity(
    kind: EntityKind | None,
    accepted: list[Partial],
    other_versions: list[Partial],
) -> RecordIdentity:
    matched = [
        (partial.candidate, _provenance(partial))
        for partial in accepted
        if isinstance(partial.candidate, RecordCandidate)
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

    bpm, bpm_conflict = _bpm(matched)
    key, key_conflict = _consensus(
        "key",
        ((c.key, normalize_key(c.key) or normalize_text(c.key), p) for c, p in matched if c.key),
    )

    version = _version([candidate for candidate, _ in matched])
    version_conflict = _version_discrepancy(version, title, other_versions)
    external_ids, id_conflicts = _external_ids(matched)
    conflicts = [
        artist_conflict,
        title_conflict,
        version_conflict,
        date_conflict,
        bpm_conflict,
        key_conflict,
        *id_conflicts,
    ]
    return RecordIdentity(
        kind=kind,
        artist=artist,
        title=title,
        version=version,
        date=date,
        bpm=bpm,
        key=key,
        labels=_labels(matched),
        isrcs=_codes(matched, lambda c: c.isrcs, normalize_code),
        upcs=_codes(matched, lambda c: c.upcs, normalize_barcode),
        copyrights=_codes(matched, lambda c: c.copyrights, normalize_copyright),
        external_ids=external_ids,
        discrepancies=[conflict for conflict in conflicts if conflict is not None],
    )


@dataclass(frozen=True, slots=True)
class _NameParts:
    """Fields artists and labels share, agreed between sources, with what sources dispute."""

    name: Sourced[str] | None
    disambiguation: Sourced[str] | None
    country: Sourced[str] | None
    location: Sourced[str] | None
    begin: Sourced[str] | None
    end: Sourced[str] | None
    external_ids: list[ExternalId]
    discrepancies: list[Discrepancy]


def _date(
    name: str,
    dates: Iterable[tuple[str | None, Provenance]],
) -> tuple[Sourced[str] | None, Discrepancy | None]:
    return _consensus(name, ((date, date[:4], p) for date, p in dates if date), _most_precise)


def _name_parts(
    matched: Sequence[tuple[ArtistCandidate | LabelCandidate, Provenance]],
    name_key: Callable[[str], str],
) -> _NameParts:
    name, name_conflict = _consensus("name", ((c.name, name_key(c.name), p) for c, p in matched))
    disambiguation, disambiguation_conflict = _consensus(
        "disambiguation",
        (
            (c.disambiguation, normalize_text(c.disambiguation), p)
            for c, p in matched
            if c.disambiguation
        ),
    )
    country, country_conflict = _consensus(
        "country",
        ((c.country, normalize_text(c.country), p) for c, p in matched if c.country),
    )
    location, location_conflict = _consensus(
        "location",
        ((c.location, normalize_text(c.location), p) for c, p in matched if c.location),
    )
    begin, begin_conflict = _date("begin", ((c.begin, p) for c, p in matched))
    end, end_conflict = _date("end", ((c.end, p) for c, p in matched))
    external_ids, id_conflicts = _external_ids(matched)
    conflicts = [
        name_conflict,
        disambiguation_conflict,
        country_conflict,
        location_conflict,
        begin_conflict,
        end_conflict,
        *id_conflicts,
    ]
    return _NameParts(
        name=name,
        disambiguation=disambiguation,
        country=country,
        location=location,
        begin=begin,
        end=end,
        external_ids=external_ids,
        discrepancies=[conflict for conflict in conflicts if conflict is not None],
    )


def _artist_identity(accepted: list[Partial]) -> ArtistIdentity:
    matched = [
        (partial.candidate, _provenance(partial))
        for partial in accepted
        if isinstance(partial.candidate, ArtistCandidate)
    ]
    parts = _name_parts(matched, normalize_artist)
    agreed, type_conflict = _consensus(
        "type",
        ((c.type, c.type, p) for c, p in matched if c.type is not None),
    )
    return ArtistIdentity(
        name=parts.name,
        disambiguation=parts.disambiguation,
        type=None
        if agreed is None
        else Sourced(value=ArtistType(agreed.value), sources=agreed.sources),
        country=parts.country,
        location=parts.location,
        begin=parts.begin,
        end=parts.end,
        external_ids=parts.external_ids,
        discrepancies=[*parts.discrepancies, *([type_conflict] if type_conflict else [])],
    )


def _label_identity(accepted: list[Partial]) -> LabelIdentity:
    matched = [
        (partial.candidate, _provenance(partial))
        for partial in accepted
        if isinstance(partial.candidate, LabelCandidate)
    ]
    parts = _name_parts(matched, normalize_text)
    return LabelIdentity(
        name=parts.name,
        disambiguation=parts.disambiguation,
        country=parts.country,
        location=parts.location,
        begin=parts.begin,
        end=parts.end,
        external_ids=parts.external_ids,
        discrepancies=parts.discrepancies,
    )


def _combine[T: Attributed](kept: T, other: T) -> T:
    return kept.model_copy(update={"sources": _union(kept.sources, other.sources)})


def _combine_tags(kept: Tag, other: Tag) -> Tag:
    weights = [weight for weight in (kept.weight, other.weight) if weight is not None]
    return _combine(kept, other).model_copy(update={"weight": max(weights, default=None)})


def _combine_links(kept: Link, other: Link) -> Link:
    """Union the sources and keep a preview that only the other link has."""
    return _combine(kept, other).model_copy(
        update={"preview_url": kept.preview_url or other.preview_url},
    )


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
    return _combine(kept, other).model_copy(
        update={
            "target": target,
            "recording_offset": kept.recording_offset
            if kept.recording_offset is not None
            else other.recording_offset,
            "target_offset": kept.target_offset
            if kept.target_offset is not None
            else other.target_offset,
            "element": kept.element or other.element,
        },
    )


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
        (relation.recording_offset, relation.target_offset)
        if relation.kind in {RelationKind.SAMPLES, RelationKind.SAMPLED_BY}
        and relation.recording_offset is not None
        else None,
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


# Shop and label texts often reprint one press release.
_COPY_KINDS = frozenset({TextKind.SHOP, TextKind.LABEL})

# Copies shorter than this many words are the same only when their bodies are equal.
_COPY_MIN_WORDS = 20

# Share of the shorter copy's five-word sequences found in the other copy.
_COPY_OVERLAP = 0.8
_RATING_TOLERANCE = 0.001


def _text_key(text: Text) -> tuple[object, ...]:
    """Texts are the same by body; scores without a body by publication, rating, and title."""
    if text.body.strip():
        kind: object = "copy" if text.kind in _COPY_KINDS else text.kind
        return (kind, normalize_text(text.body))
    publication = normalize_text(text.publication or "")
    return (text.kind, "", publication, text.rating, normalize_text(text.title or ""))


def _copy_key(text: Text) -> str | None:
    if text.kind not in _COPY_KINDS:
        return None
    return normalize_text(strip_ellipsis(text.body)) or None


def _same_copy(first: str, second: str) -> bool:
    """Tell whether two long copy keys are one text, one of them cut short or extended."""
    shorter, longer = sorted((first, second), key=len)
    if len(shorter.split()) < _COPY_MIN_WORDS:
        return False
    return f" {shorter} " in f" {longer} " or shingle_overlap(shorter, longer) >= _COPY_OVERLAP


def _combine_texts(kept: Text, other: Text) -> Text:
    """Keep the longer body; a label's copy names the text a label text."""
    if kept.kind not in _COPY_KINDS or other.kind not in _COPY_KINDS:
        return _combine(kept, other)
    longer, shorter = (other, kept) if len(other.body) > len(kept.body) else (kept, other)
    return longer.model_copy(
        update={
            "kind": TextKind.LABEL if TextKind.LABEL in {kept.kind, other.kind} else kept.kind,
            "title": longer.title or shorter.title,
            "author": longer.author or shorter.author,
            "publication": longer.publication or shorter.publication,
            "date": longer.date or shorter.date,
            "scope": kept.scope,
            "sources": _union(kept.sources, other.sources),
        },
    )


def _merge_copies(texts: Iterable[Text]) -> list[Text]:
    """Merge shop and label texts that repeat one press release, keeping every source."""
    merged: list[Text] = []
    keys: list[str | None] = []
    for text in texts:
        key = _copy_key(text)
        index = next(
            (
                position
                for position, known in enumerate(keys)
                if key is not None and known is not None and _same_copy(known, key)
            ),
            None,
        )
        if index is None:
            merged.append(text)
            keys.append(key)
        else:
            merged[index] = _combine_texts(merged[index], text)
            keys[index] = _copy_key(merged[index])
    return merged


def _merge_review_scores(texts: Iterable[Text]) -> list[Text]:
    """Attach a secondary score citation to its matching review text."""
    merged: list[Text] = []
    for text in texts:
        index = next(
            (
                i
                for i, known in enumerate(merged)
                if text.kind is known.kind is TextKind.REVIEW
                and bool(text.body) != bool(known.body)
                and normalize_text(text.publication or "")
                == normalize_text(known.publication or "")
                and text.scope is known.scope
                and text.rating is not None
                and known.rating is not None
                and text.rating.value is not None
                and known.rating.value is not None
                and text.rating.scale is not None
                and known.rating.scale is not None
                and abs(
                    text.rating.value / text.rating.scale - known.rating.value / known.rating.scale,
                )
                < _RATING_TOLERANCE
            ),
            None,
        )
        if index is None:
            merged.append(text)
        else:
            full = text if text.body else merged[index]
            empty = merged[index] if text.body else text
            merged[index] = full.model_copy(
                update={"sources": _union(full.sources, empty.sources)},
            )
    return merged


def _facts(kind: EntityKind, accepted: list[Partial], other_versions: list[Partial]) -> Facts:
    scope_rank = _scope_rank(kind)

    tags = _dedupe(
        (tag for p in accepted for tag in p.tags),
        lambda t: (normalize_text(t.name), t.context_url),
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

    deduped_texts = _dedupe((text for p in accepted for text in p.texts), _text_key, _combine_texts)
    texts = _merge_review_scores(_merge_copies(deduped_texts))

    found_relations = (relation for p in accepted for relation in p.relations)
    version_relations = (
        _other_version_relation(p, p.candidate)
        for p in other_versions
        if isinstance(p.candidate, RecordCandidate)
    )
    relations = _dedupe((*found_relations, *version_relations), _relation_key, _combine_relations)
    metrics = _dedupe((metric for p in accepted for metric in p.metrics), _metric_key)

    links = _dedupe(
        (link for p in accepted for link in p.links),
        lambda link: _url_key(link.url),
        _combine_links,
    )
    review_links = _dedupe(
        (link for p in accepted for link in p.review_links),
        lambda link: _url_key(link.url),
    )
    link_order = _LINK_ORDER[kind]
    return Facts(
        tags=sorted(tags, key=lambda t: (scope_rank(t), -len(t.sources), -(t.weight or 0.0))),
        credits=sorted(credit_facts, key=scope_rank),
        texts=sorted(texts, key=lambda t: (scope_rank(t), _TEXT_ORDER.index(t.kind))),
        relations=sorted(relations, key=lambda r: (_RELATION_ORDER.index(r.kind), scope_rank(r))),
        metrics=sorted(metrics, key=scope_rank),
        links=sorted(links, key=lambda link: link_order.index(link.target)),
        review_links=review_links,
    )


def merge(
    query: Query,
    partials: Sequence[Partial],
    errors: Iterable[AdapterError] = (),
    *,
    generated_at: datetime,
) -> Dossier:
    """Build a dossier from adapter results, keeping only facts about the queried version."""
    reference = _reference(query, partials)
    trace(
        logger,
        TraceEvent.MERGE_REFERENCE,
        reference=None if reference is None else reference.describe(),
        partials=len(partials),
    )
    judgement = _judge(reference, partials)
    identity = build_identity(query, judgement.accepted, judgement.other_versions)
    facts = _facts(identity.kind or EntityKind.TRACK, judgement.accepted, judgement.other_versions)
    return Dossier(
        query=query,
        identity=identity,
        **dict(facts),
        errors=[*errors, *judgement.errors],
        generated_at=generated_at,
    )
