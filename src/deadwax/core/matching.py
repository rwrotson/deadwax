import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from deadwax.core.events import TraceEvent, trace
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

# Words that make one remixer's version another cut of it, such as 'Extended Remix'.
_CUTS = frozenset({"extended", "radio", "dub", "instrumental", "intro"})

# A trailing bracket left after version markers, such as an alternative title.
_TRAILING_BRACKET = re.compile(r"^(?P<title>.*\S)\s*[\(\[](?P<inner>[^()\[\]]+)[\)\]]\s*$")

# Shorter bracket text is more often an unmarked mix name, such as 'Tee Beat', than a title.
_ALTERNATIVE_TITLE_WORDS = 3

# Bracket words that tell recordings apart, so the bracket stays part of the title.
_DISTINCT_BRACKET = re.compile(
    r"\b(?:part|pt|no|vol|volume|chapter|movement|act|op|reprise|interlude|intro|outro|"
    r"prelude|version|mix|take|session|recording|demo|\d+|[ivx]+)\b",
)

logger = logging.getLogger(__name__)


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

    def describe(self) -> dict[str, object]:
        """Return the key as JSON values for trace events."""
        version = self.resolved_version
        label = str(version.kind) if version.detail is None else f"{version.kind}: {version.detail}"
        return {"artist": self.artist, "title": self.title, "kind": self.kind, "version": label}


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


def _title_keys(title: str) -> set[str]:
    """Return the title key, and the key without a trailing alternative title in brackets."""
    base = parse_title(title).base
    keys = {normalize_text(base)}
    if (bracket := _TRAILING_BRACKET.match(base)) is not None:
        inner = normalize_text(bracket["inner"])
        if len(inner.split()) >= _ALTERNATIVE_TITLE_WORDS and not _DISTINCT_BRACKET.search(inner):
            keys.add(normalize_text(bracket["title"]))
    return keys


def title_similarity(left: str, right: str) -> float:
    """Compare titles without version markers, featured artists, and alternative titles."""
    return max(
        key_similarity(left_key, right_key)
        for left_key in _title_keys(left)
        for right_key in _title_keys(right)
    )


def same_version(left: VersionInfo, right: VersionInfo) -> bool:
    """Whether two versions denote the same recording or release variant."""
    if left.kind != right.kind:
        return False
    if left.kind not in _DETAILED_KINDS or left.detail is None or right.detail is None:
        return True
    left_detail, right_detail = normalize_text(left.detail), normalize_text(right.detail)
    if _CUTS.intersection(left_detail.split()) != _CUTS.intersection(right_detail.split()):
        return False
    return key_similarity(left_detail, right_detail) >= _DETAIL_THRESHOLD


def compare(reference: RecordKey, candidate: RecordKey) -> Match:
    """Decide whether a candidate is the reference record, another version of it, or unrelated."""
    artist_score = artist_similarity(reference.artist, candidate.artist)
    title_score = title_similarity(reference.title, candidate.title)
    failed: list[str] = []
    if None not in (reference.kind, candidate.kind) and reference.kind != candidate.kind:
        failed.append("kind")
    if artist_score < ARTIST_THRESHOLD:
        failed.append("artist")
    if title_score < TITLE_THRESHOLD:
        failed.append("title")
    if failed:
        verdict = Verdict.NO_MATCH
    elif same_version(reference.resolved_version, candidate.resolved_version):
        verdict = Verdict.MATCH
    else:
        verdict = Verdict.OTHER_VERSION

    trace(
        logger,
        TraceEvent.MATCH_COMPARE,
        reference=reference.describe(),
        candidate=candidate.describe(),
        artist_score=round(artist_score, 3),
        title_score=round(title_score, 3),
        verdict=verdict,
        failed=failed,
    )
    return Match(verdict=verdict, artist_score=artist_score, title_score=title_score)
