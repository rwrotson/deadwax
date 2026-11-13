import re
from dataclasses import dataclass, field

from deadwax.core.models import VersionInfo, VersionKind
from deadwax.core.normalize import split_featuring
from deadwax.core.query import DASHES

# Whole-marker forms checked first, because 'Original Mix' or 'Radio Edit' also contain keywords.
# An explicit version is the uncensored original; a clean one is the censored edit.
_EXACT_RULES: tuple[tuple[VersionKind, re.Pattern[str]], ...] = (
    (
        VersionKind.ORIGINAL,
        re.compile(
            r"^(?:(?:original|album)(?: mix| version)?|explicit(?: version)?)$",
            re.IGNORECASE,
        ),
    ),
    (
        VersionKind.EDIT,
        re.compile(
            r"^(?:(?:radio|single|extended|short|clean)(?: edit| mix| version)?|edit)$",
            re.IGNORECASE,
        ),
    ),
)

_KEYWORD_RULES: tuple[tuple[VersionKind, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern, re.IGNORECASE))
    for kind, pattern in (
        (VersionKind.REMASTER, r"\bremaster(?:ed)?\b"),
        (VersionKind.LIVE, r"\blive\b"),
        (VersionKind.DEMO, r"\bdemo\b"),
        (VersionKind.INSTRUMENTAL, r"\binstrumental\b"),
        (VersionKind.ACOUSTIC, r"\b(?:acoustic|unplugged)\b"),
        (VersionKind.COVER, r"\bcover\b"),
        (
            VersionKind.REMIX,
            r"\b(?:remix|rmx|re-?mix|rework|re-?edit|dub|vip|bootleg|flip|refix|mix)\b",
        ),
        (VersionKind.REISSUE, r"\b(?:deluxe|expanded|anniversary|reissue)\b"),
        (
            VersionKind.ALTERNATE,
            r"\b(?:alternate|alternative|alt\.|take \d+|mono|outtake|rehearsal)\b",
        ),
    )
)

# The most distinctive version wins when one title or marker names several.
_PRIORITY = (
    VersionKind.REMIX,
    VersionKind.LIVE,
    VersionKind.DEMO,
    VersionKind.COVER,
    VersionKind.INSTRUMENTAL,
    VersionKind.ACOUSTIC,
    VersionKind.EDIT,
    VersionKind.ALTERNATE,
    VersionKind.REISSUE,
    VersionKind.REMASTER,
    VersionKind.ORIGINAL,
)

_BRACKETED = re.compile(r"\s*[\(\[]([^()\[\]]+)[\)\]]")
_DASH_SUFFIX = re.compile(rf"\s+[{DASHES}]\s+([^{DASHES}]+)$")


@dataclass(frozen=True, slots=True)
class ParsedTitle:
    """Title split into its base, version, and featured artists."""

    base: str
    version: VersionInfo
    featured: list[str] = field(default_factory=list)


def classify_marker(marker: str) -> VersionKind | None:
    """Return the version a title marker such as 'Live at Leeds' denotes, if any."""
    marker = marker.strip()
    for kind, pattern in _EXACT_RULES:
        if pattern.match(marker):
            return kind
    kinds = [kind for kind, pattern in _KEYWORD_RULES if pattern.search(marker)]
    return min(kinds, key=_PRIORITY.index) if kinds else None


def _pick(markers: list[tuple[VersionKind, str]]) -> VersionInfo:
    if not markers:
        return VersionInfo()
    kind, detail = min(markers, key=lambda marker: _PRIORITY.index(marker[0]))
    return VersionInfo(kind=kind, detail=detail)


def parse_title(title: str) -> ParsedTitle:
    """Split a title into base title and version, from bracketed or dash-separated markers."""
    base, featured = split_featuring(title)
    markers: list[tuple[VersionKind, str]] = []

    def take(match: re.Match[str]) -> str:
        kind = classify_marker(match[1])
        if kind is None:
            return match[0]
        markers.append((kind, match[1].strip()))
        return ""

    base = _BRACKETED.sub(take, base)
    base = _DASH_SUFFIX.sub(take, base)
    base = base.strip() or title.strip()
    return ParsedTitle(base=base, version=_pick(markers), featured=featured)
