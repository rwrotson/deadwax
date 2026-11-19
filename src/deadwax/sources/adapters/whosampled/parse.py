import re
from urllib.parse import quote

from deadwax.core import (
    NotFoundError,
    Query,
    RecordKey,
    RelationKind,
)

ROOT = "https://www.whosampled.com"
MIN_CELLS = 3
MIN_SAMPLE_BOXES = 2
SECTION_KINDS = {
    "Contains samples": RelationKind.SAMPLES,
    "Sampled in": RelationKind.SAMPLED_BY,
    "Contains a cover": RelationKind.COVER_OF,
    "Covered in": RelationKind.COVERED_BY,
    "Contains a remix": RelationKind.REMIX_OF,
    "Remixed in": RelationKind.REMIXED_BY,
}


def offset(value: str | None) -> int | None:
    """Seconds of a sample timestamp such as '1:23'."""
    if value is None or not re.fullmatch(r"\d+(?::\d{1,2}){1,2}", value):
        return None
    result = 0
    for part in value.split(":"):
        result = result * 60 + int(part)
    return result


def _slug(value: str) -> str:
    return quote(re.sub(r"\s+", "-", value.strip()), safe="-'()")


def record_url(query: Query, key: RecordKey | None) -> str:
    """WhoSampled page of the queried recording."""
    if query.url is not None and "whosampled.com" in query.url:
        return query.url
    if key is not None:
        return f"{ROOT}/{_slug(key.artist)}/{_slug(key.title)}/"
    raise NotFoundError("WhoSampled needs an artist and track title")
