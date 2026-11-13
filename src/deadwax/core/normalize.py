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
