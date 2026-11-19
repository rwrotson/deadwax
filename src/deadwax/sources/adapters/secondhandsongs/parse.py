from collections.abc import Iterable, Mapping

from deadwax.core import (
    Credit,
    Entity,
    EntityKind,
    EntityType,
    Provenance,
    RecordCandidate,
    RecordKey,
    Relation,
    RelationKind,
    Scope,
    Verdict,
    compare,
)
from deadwax.sources._search import SearchHit
from deadwax.sources.adapters.secondhandsongs import models

SOURCE = "secondhandsongs"
API_HOST = "https://api.secondhandsongs.com"
WEBSITE = "https://secondhandsongs.com"
WRITER = "writer"
ORIGINAL = "original"
FIRST_PERFORMANCE = "first performance"
ADAPTATION = "adaptation"


def website(uri: str) -> str:
    """Page of an API entity on the website."""
    return WEBSITE + uri.removeprefix(API_HOST) if uri.startswith(API_HOST) else uri


def _performer(performance: models.PerformanceRef | models.Performance) -> str | None:
    return performance.performer.name if performance.performer is not None else None


def search_hits(results: models.SearchResults) -> list[SearchHit]:
    """Search results as records for the matching gate; results without a performer are dropped."""
    return [
        SearchHit(url=hit.uri, key=RecordKey(artist=artist, title=hit.title, kind=EntityKind.TRACK))
        for hit in results.result_page
        if (artist := _performer(hit)) is not None
    ]


def candidate(performance: models.Performance) -> RecordCandidate:
    """Describe a performance; its date is the first release's when known."""
    return RecordCandidate(
        kind=EntityKind.TRACK,
        artist=_performer(performance) or "",
        title=performance.title,
        date=performance.first_release_date or performance.date,
        url=website(performance.uri),
    )


def _recording(performance: models.PerformanceRef, date: str | None = None) -> Entity:
    return Entity(
        type=EntityType.RECORDING,
        name=performance.title,
        artist=_performer(performance),
        date=date,
        url=website(performance.uri),
    )


def _work(work: models.WorkRef | models.Work) -> Entity:
    return Entity(type=EntityType.WORK, name=work.title, url=website(work.uri))


def covers(performance: models.Performance, limit: int) -> list[Relation]:
    """Covers of an original performance."""
    sources = [Provenance(source=SOURCE, url=website(performance.uri))]
    return [
        Relation(
            kind=RelationKind.COVERED_BY,
            target=_recording(cover),
            scope=Scope.WORK,
            sources=sources,
        )
        for cover in performance.covers[:limit]
    ]


def _date(performance: models.Performance | None) -> str | None:
    if performance is None:
        return None
    return performance.first_release_date or performance.date


def same_artist(left: models.Performance, right: models.PerformanceRef) -> bool:
    """Whether two performances are by the same artist, as the matching gate compares artists."""
    artist, other = _performer(left), _performer(right)
    if artist is None or other is None:
        return False
    found = compare(
        RecordKey(artist=artist, title=left.title),
        RecordKey(artist=other, title=left.title),
    )
    return found.verdict is not Verdict.NO_MATCH


def originals(
    performance: models.Performance,
    found: Mapping[str, models.Performance],
    limit: int,
) -> list[Relation]:
    """Relate a non-original performance to the originals of its works.

    A later recording by the original artist is another version of the first performance and
    shares its covers; any other performance is a cover of the work and its original.
    """
    sources = [Provenance(source=SOURCE, url=website(performance.uri))]
    result = []
    for work in performance.originals:
        original = found.get(work.original.uri) if work.original is not None else None
        if work.original is not None and same_artist(performance, work.original):
            result.append(
                Relation(
                    kind=RelationKind.OTHER_VERSION,
                    target=_recording(work.original, _date(original)),
                    note=FIRST_PERFORMANCE,
                    scope=Scope.RECORDING,
                    sources=sources,
                ),
            )
            if original is not None:
                result += covers(original, limit)
            continue
        result.append(
            Relation(
                kind=RelationKind.COVER_OF,
                target=_work(work),
                scope=Scope.WORK,
                sources=sources,
            ),
        )
        if work.original is not None:
            result.append(
                Relation(
                    kind=RelationKind.COVER_OF,
                    target=_recording(work.original, _date(original)),
                    note=ORIGINAL,
                    scope=Scope.RECORDING,
                    sources=sources,
                ),
            )
    return result


def writers(work: models.Work) -> list[Credit]:
    """Writers of a work."""
    sources = [Provenance(source=SOURCE, url=website(work.uri))]
    return [
        Credit(role=WRITER, name=writer.common_name, scope=Scope.WORK, sources=sources)
        for writer in work.credits
    ]


def adaptations(work: models.Work) -> list[Relation]:
    """Works the work adapts and works adapting it, such as translations."""
    sources = [Provenance(source=SOURCE, url=website(work.uri))]
    found: Iterable[tuple[RelationKind, models.WorkRef]] = (
        *((RelationKind.COVER_OF, based_on) for based_on in work.based_on),
        *((RelationKind.COVERED_BY, derived) for derived in work.derived_works),
    )
    return [
        Relation(
            kind=kind,
            target=_work(other),
            note=ADAPTATION,
            scope=Scope.WORK,
            sources=sources,
        )
        for kind, other in found
    ]
