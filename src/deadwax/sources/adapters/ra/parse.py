import re
from urllib.parse import urlsplit

from deadwax.core import (
    EntityKind,
    Provenance,
    RecordCandidate,
    RecordKey,
    Scope,
    Text,
    TextKind,
    Verdict,
    compare,
)
from deadwax.sources._html import parse_html, text_of

_REVIEW_ID = re.compile(r"^/reviews/(\d+)/?$")
QUERY = """query DEADWAX_REVIEW($id: ID!) {
  review(id: $id) {
    id title type content date contentUrl
    author { id name }
    labels { id name contentUrl blurb }
    artists { id name contentUrl biography { id blurb } }
  }
}"""
SEARCH_QUERY = """query DEADWAX_SEARCH($term: String!) {
  search(searchTerm: $term, indices: [REVIEW], limit: 10) {
    id value contentUrl searchType reviewType
  }
}"""


def as_object(value: object) -> dict[str, object]:
    """The value as a JSON object, or an empty one."""
    return value if isinstance(value, dict) else {}


def as_text(value: object) -> str | None:
    """The value if it is non-blank text."""
    return value if isinstance(value, str) and value.strip() else None


def _html_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return text_of(parse_html(value).body)


def review_id(url: str) -> str | None:
    """Identifier of a Resident Advisor review URL."""
    host = (urlsplit(url).hostname or "").lower()
    match = _REVIEW_ID.fullmatch(urlsplit(url).path)
    return match[1] if host in {"ra.co", "www.ra.co"} and match is not None else None


def extract(
    record: dict[str, object],
    key: RecordKey,
    url: str,
) -> tuple[RecordCandidate, list[Text]] | None:
    """Read the reviewed record and its texts if it matches the record."""
    artists = record.get("artists")
    first_artist = as_object(artists[0]) if isinstance(artists, list) and artists else {}
    artist = as_text(first_artist.get("name"))
    title = as_text(record.get("title"))
    if not artist or not title:
        return None
    title = title.removeprefix(f"{artist} - ").strip()
    kind = EntityKind.ALBUM if record.get("type") == "ALBUM" else EntityKind.TRACK
    found_key = RecordKey(artist=artist, title=title, kind=kind)
    if compare(key, found_key).verdict is not Verdict.MATCH:
        return None
    candidate = RecordCandidate(kind=kind, artist=artist, title=title, url=url)
    provenance = Provenance(source="ra", url=url)
    scope = Scope.RELEASE_GROUP if kind is EntityKind.ALBUM else Scope.RECORDING
    texts = []
    body = _html_text(record.get("content"))
    if body:
        texts.append(
            Text(
                kind=TextKind.REVIEW,
                body=body,
                author=as_text(as_object(record.get("author")).get("name")),
                publication="Resident Advisor",
                date=as_text(record.get("date")),
                scope=scope,
                sources=[provenance],
            ),
        )
    biography = _html_text(as_object(first_artist.get("biography")).get("blurb"))
    if biography:
        texts.append(
            Text(
                kind=TextKind.EDITORIAL,
                body=biography,
                title=artist,
                publication="Resident Advisor",
                scope=Scope.ARTIST,
                sources=[provenance],
            ),
        )
    labels = record.get("labels")
    for label_value in labels if isinstance(labels, list) else []:
        label = as_object(label_value)
        label_body = _html_text(label.get("blurb"))
        if label_body:
            texts.append(
                Text(
                    kind=TextKind.EDITORIAL,
                    body=label_body,
                    title=as_text(label.get("name")),
                    publication="Resident Advisor",
                    scope=Scope.LABEL,
                    sources=[provenance],
                ),
            )
    return candidate, texts
