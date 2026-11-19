from collections import Counter
from collections.abc import Iterable, Sequence

from deadwax.core.adapter import Capability
from deadwax.core.models import Attributed, Dossier, EntityType, Relation, RelationKind
from deadwax.core.request import RelationLimit, Request


def _first_source(fact: Attributed) -> str | None:
    return fact.sources[0].source if fact.sources else None


def _capped[T: Attributed](facts: Iterable[T], cap: int) -> list[T]:
    seen: Counter[str | None] = Counter()
    kept: list[T] = []
    for fact in facts:
        source = _first_source(fact)
        if seen[source] < cap:
            seen[source] += 1
            kept.append(fact)
    return kept


def _relations(relations: Sequence[Relation], limits: tuple[RelationLimit, ...]) -> list[Relation]:
    seen: Counter[tuple[str | None, RelationKind, EntityType]] = Counter()
    kept: list[Relation] = []
    for relation in relations:
        limit = next((li for li in limits if li.covers(relation.kind, relation.target.type)), None)
        if limit is None:
            continue
        key = (_first_source(relation), relation.kind, relation.target.type)
        if seen[key] < limit.per_source:
            seen[key] += 1
            kept.append(relation)
    return kept


def trim(dossier: Dossier, request: Request) -> Dossier:
    """Keep only the facts a request asked for, within its caps.

    A fact found by several sources counts against the cap of its first source.
    """
    tags = dossier.tags if request.wants(Capability.TAGS) else []
    if request.tags_per_source is not None:
        tags = _capped(tags, request.tags_per_source)

    relations = dossier.relations if request.wants(Capability.RELATIONS) else []
    if request.relations is not None:
        relations = _relations(relations, request.relations)

    links = dossier.links
    if not request.wants(Capability.LINKS):
        wants_previews = request.wants(Capability.PREVIEWS)
        links = [link for link in links if wants_previews and link.preview_url is not None]

    texts = request.wants(Capability.TEXTS)
    return dossier.model_copy(
        update={
            "tags": tags,
            "credits": dossier.credits if request.wants(Capability.CREDITS) else [],
            "texts": dossier.texts if texts else [],
            "review_links": dossier.review_links if texts else [],
            "relations": relations,
            "metrics": dossier.metrics if request.wants(Capability.METRICS) else [],
            "links": links,
        },
    )
