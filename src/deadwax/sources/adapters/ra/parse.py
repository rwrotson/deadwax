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
from deadwax.sources.adapters.ra.models import Review

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


def _html_text(value: str | None) -> str | None:
    return text_of(parse_html(value).body) if value is not None else None


def review_id(url: str) -> str | None:
    """Identifier of a Resident Advisor review URL."""
    host = (urlsplit(url).hostname or "").lower()
    match = _REVIEW_ID.fullmatch(urlsplit(url).path)
    return match[1] if host in {"ra.co", "www.ra.co"} and match is not None else None


def extract(
    record: Review,
    key: RecordKey,
    url: str,
) -> tuple[RecordCandidate, list[Text]] | None:
    """Read the reviewed record and its texts if it matches the record."""
    if not record.artists:
        return None
    first_artist = record.artists[0]
    artist = first_artist.name
    title = record.title
    if not artist or not title:
        return None
    title = title.removeprefix(f"{artist} - ").strip()
    kind = EntityKind.ALBUM if record.type == "ALBUM" else EntityKind.TRACK
    found_key = RecordKey(artist=artist, title=title, kind=kind)
    if compare(key, found_key).verdict is not Verdict.MATCH:
        return None
    candidate = RecordCandidate(kind=kind, artist=artist, title=title, url=url)
    provenance = Provenance(source="ra", url=url)
    scope = Scope.RELEASE_GROUP if kind is EntityKind.ALBUM else Scope.RECORDING
    texts = []
    body = _html_text(record.content)
    if body:
        texts.append(
            Text(
                kind=TextKind.REVIEW,
                body=body,
                author=record.author.name,
                publication="Resident Advisor",
                date=record.date,
                scope=scope,
                sources=[provenance],
            ),
        )
    biography = _html_text(first_artist.biography.blurb)
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
    for label in record.labels:
        label_body = _html_text(label.blurb)
        if label_body:
            texts.append(
                Text(
                    kind=TextKind.EDITORIAL,
                    body=label_body,
                    title=label.name,
                    publication="Resident Advisor",
                    scope=Scope.LABEL,
                    sources=[provenance],
                ),
            )
    return candidate, texts
