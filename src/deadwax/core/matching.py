from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from deadwax.core.models import VersionInfo, VersionKind
from deadwax.core.normalize import normalize_artist, normalize_text, split_artists
from deadwax.core.query import EntityKind
from deadwax.core.versions import parse_title

ARTIST_THRESHOLD = 0.85
TITLE_THRESHOLD = 0.85

# Score for an artist found as one name of a collaboration rather than the whole credit.
COLLABORATION_SCORE = 0.9

# Versions whose marker names a person or event: different details mean different recordings.
_DETAILED_KINDS = frozenset({VersionKind.REMIX, VersionKind.LIVE})
_DETAIL_THRESHOLD = 0.6


class Verdict(StrEnum):
    """Outcome of comparing a candidate with the reference record."""

    MATCH = "match"
    OTHER_VERSION = "other_version"
    NO_MATCH = "no_match"


@dataclass(frozen=True, slots=True)
class RecordKey:
    """Fields that identify a record for matching."""

    artist: str
    title: str
    kind: EntityKind | None = None
    version: VersionInfo | None = None

    @property
    def resolved_version(self) -> VersionInfo:
        """Explicit version, or the one derived from the title."""
        return self.version if self.version is not None else parse_title(self.title).version


@dataclass(frozen=True, slots=True)
class Match:
    """Scores and verdict of one comparison."""

    verdict: Verdict
    artist_score: float
    title_score: float


def key_similarity(left: str, right: str) -> float:
    """Compare two normalized keys by characters and by sorted words, from 0 to 1."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    by_characters = SequenceMatcher(None, left, right).ratio()
    by_words = SequenceMatcher(
        None,
        " ".join(sorted(left.split())),
        " ".join(sorted(right.split())),
    )
    return max(by_characters, by_words.ratio())


def artist_similarity(left: str, right: str) -> float:
    """Compare artist credits, accepting one name of a collaboration."""
    left_key, right_key = normalize_artist(left), normalize_artist(right)
    score = key_similarity(left_key, right_key)
    if score < 1.0 and (
        left_key in split_artists(right_key) or right_key in split_artists(left_key)
    ):
        score = max(score, COLLABORATION_SCORE)
    return score


def title_similarity(left: str, right: str) -> float:
    """Compare titles without version markers and featured artists."""
    return key_similarity(
        normalize_text(parse_title(left).base),
        normalize_text(parse_title(right).base),
    )


def same_version(left: VersionInfo, right: VersionInfo) -> bool:
    """Whether two versions denote the same recording or release variant."""
    if left.kind != right.kind:
        return False
    if left.kind not in _DETAILED_KINDS or left.detail is None or right.detail is None:
        return True
    detail_score = key_similarity(normalize_text(left.detail), normalize_text(right.detail))
    return detail_score >= _DETAIL_THRESHOLD


def compare(reference: RecordKey, candidate: RecordKey) -> Match:
    """Decide whether a candidate is the reference record, another version of it, or unrelated."""
    artist_score = artist_similarity(reference.artist, candidate.artist)
    title_score = title_similarity(reference.title, candidate.title)
    kinds_differ = None not in (reference.kind, candidate.kind) and reference.kind != candidate.kind
    if kinds_differ or artist_score < ARTIST_THRESHOLD or title_score < TITLE_THRESHOLD:
        verdict = Verdict.NO_MATCH
    elif same_version(reference.resolved_version, candidate.resolved_version):
        verdict = Verdict.MATCH
    else:
        verdict = Verdict.OTHER_VERSION
    return Match(verdict=verdict, artist_score=artist_score, title_score=title_score)
