import re
import unicodedata

from deadwax.core.query import DASHES, QUOTES

_PUNCTUATION_FOLD = str.maketrans({**dict.fromkeys(DASHES, "-"), **dict.fromkeys(QUOTES, "'")})

# Latin letters that Unicode does not decompose into a base letter and a mark.
_LATIN_LETTERS = str.maketrans(
    {"ø": "o", "đ": "d", "ł": "l", "ħ": "h", "\u0131": "i", "æ": "ae", "œ": "oe", "þ": "th"},
)

_FEATURING = r"(?:feat\.?|ft\.?|featuring)"
_FEATURING_BRACKETED = re.compile(rf"\s*[\(\[]{_FEATURING}\s+([^()\[\]]+)[\)\]]", re.IGNORECASE)
_FEATURING_TRAILING = re.compile(rf"\s+{_FEATURING}\s+(.+)$", re.IGNORECASE)
_ARTIST_SEPARATOR = re.compile(r"\s*(?:,|&|\+|\band\b|\bx\b|\bvs\.?|\bwith\b)\s*")

# Leading mark of a folded copyright line: phonographic (℗, (p)) or plain (©, (c), copyright).
_COPYRIGHT_MARK = re.compile(r"^\s*(?:(?P<p>℗|\(p\))|©|\(c\)|copyright\b)\s*")

# A trailing ellipsis marks a text cut short by its publisher.
_TRAILING_ELLIPSIS = re.compile(r"\s*(?:\u2026|\.{3})\s*$")

_PITCHES = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
_ACCIDENTALS = {"": 0, "#": 1, "♯": 1, "b": -1, "♭": -1}
_MINOR = frozenset({"m", "min", "minor"})
_KEY_NAME = re.compile(r"^([a-g])\s*([#♯b♭]?)\s*(major|maj|minor|min|m)?$")

# Camelot wheel ('8A' is A minor, '8B' C major) and Open Key ('1m' A minor, '1d' C major), each
# with the number of the wheel's position of C major.
_WHEELS = (
    (re.compile(r"^(1[0-2]|[1-9])\s*([ab])$"), "a", 8),
    (re.compile(r"^(1[0-2]|[1-9])\s*([dm])$"), "m", 1),
)


def _strip_latin_marks(text: str) -> str:
    """Drop diacritics from Latin letters only, so Cyrillic й or Japanese ガ stay intact."""
    kept: list[str] = []
    previous_is_latin = False
    for char in unicodedata.normalize("NFD", text):
        if unicodedata.combining(char):
            if not previous_is_latin:
                kept.append(char)
            continue
        previous_is_latin = "LATIN" in unicodedata.name(char, "")
        kept.append(char)
    return unicodedata.normalize("NFC", "".join(kept))


def fold(text: str) -> str:
    """Fold compatibility forms, case, dash and quote variants, and Latin diacritics."""
    text = unicodedata.normalize("NFKC", text).translate(_PUNCTUATION_FOLD).casefold()
    return _strip_latin_marks(text).translate(_LATIN_LETTERS)


def normalize_text(text: str) -> str:
    """Build a comparison key: folded words of any script separated by single spaces."""
    folded = fold(text).replace("&", " and ")
    return " ".join("".join(char if char.isalnum() else " " for char in folded).split())


def strip_ellipsis(text: str) -> str:
    """Remove the ellipsis that ends a shortened text."""
    return _TRAILING_ELLIPSIS.sub("", text)


def shingle_overlap(first: str, second: str, size: int = 5) -> float:
    """Share of the shorter key's word n-grams that the other key contains."""
    shingles = [_shingles(key.split(), size) for key in (first, second)]
    smaller = min(shingles, key=len)
    if not smaller:
        return 0.0
    return len(shingles[0] & shingles[1]) / len(smaller)


def _shingles(words: list[str], size: int) -> frozenset[tuple[str, ...]]:
    return frozenset(tuple(words[i : i + size]) for i in range(len(words) - size + 1))


def split_featuring(text: str) -> tuple[str, list[str]]:
    """Separate 'feat.' credits from an artist or title."""
    featured = [match.strip() for match in _FEATURING_BRACKETED.findall(text)]
    text = _FEATURING_BRACKETED.sub("", text)
    trailing = _FEATURING_TRAILING.search(text)
    if trailing is not None:
        featured.append(trailing[1].strip())
        text = text[: trailing.start()]
    return text.strip(), featured


def normalize_artist(text: str) -> str:
    """Build an artist comparison key without featured artists or a leading 'The'."""
    key = normalize_text(split_featuring(text)[0])
    return key.removeprefix("the ") if key != "the" else key


def split_artists(key: str) -> list[str]:
    """Split a normalized artist key into the names of a collaboration."""
    return [part for part in _ARTIST_SEPARATOR.split(key) if part]


def normalize_code(code: str) -> str:
    """Normalize an ISRC or catalog number: uppercase without spaces, dots, or hyphens."""
    return re.sub(r"[\s.\-]", "", unicodedata.normalize("NFKC", code)).upper()


def normalize_barcode(code: str) -> str:
    """Normalize a UPC or EAN so that the 12- and 13-digit forms compare equal."""
    return "".join(char for char in code if char.isdigit()).lstrip("0")


def normalize_copyright(line: str) -> str:
    """Build a copyright line key that tells ℗ from © and ignores how the mark is written."""
    folded = fold(line)
    mark = _COPYRIGHT_MARK.match(folded)
    kind = "" if mark is None else "p" if mark["p"] else "c"
    rest = folded[mark.end() :] if mark is not None else folded
    return f"{kind}|{normalize_text(rest)}"


def normalize_key(key: str) -> str | None:
    """Build a musical key comparison key of pitch class and mode; enharmonics compare equal."""
    text = " ".join(unicodedata.normalize("NFKC", key).casefold().split())
    for pattern, minor_letter, c_major in _WHEELS:
        if match := pattern.match(text):
            minor = match[2] == minor_letter
            # Each step on a wheel is a fifth; the relative minor sits a minor third below.
            pitch = (7 * (int(match[1]) - c_major) + (9 if minor else 0)) % 12
            return f"{pitch}|{'minor' if minor else 'major'}"
    if match := _KEY_NAME.match(text):
        pitch = (_PITCHES[match[1]] + _ACCIDENTALS[match[2]]) % 12
        return f"{pitch}|{'minor' if match[3] in _MINOR else 'major'}"
    return None
