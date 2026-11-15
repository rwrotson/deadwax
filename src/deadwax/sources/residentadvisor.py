import json
import re
from urllib.parse import urlsplit

from deadwax.core import (
    Capability,
    EntityKind,
    LookupContext,
    NotFoundError,
    Partial,
    Pass,
    Provenance,
    Query,
    RecordCandidate,
    RecordKey,
    Scope,
    SourceError,
    SourceGroup,
    Text,
    TextKind,
    Verdict,
    compare,
)
from deadwax.sources._base import HttpAdapter, search_key
from deadwax.sources._html import parse_html, text_of
from deadwax.sources._http import Profile

_REVIEW_ID = re.compile(r"^/reviews/(\d+)/?$")
_QUERY = """query DEADWAX_REVIEW($id: ID!) {
  review(id: $id) {
    id title type content date contentUrl
    author { id name }
    labels { id name contentUrl blurb }
    artists { id name contentUrl biography { id blurb } }
  }
}"""
_SEARCH_QUERY = """query DEADWAX_SEARCH($term: String!) {
  search(searchTerm: $term, indices: [REVIEW], limit: 10) {
    id value contentUrl searchType reviewType
  }
}"""


def _object(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _html_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return text_of(parse_html(value).body)


def _review_id(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    match = _REVIEW_ID.fullmatch(urlsplit(url).path)
    return match[1] if host in {"ra.co", "www.ra.co"} and match is not None else None


def _extract(
    record: dict[str, object],
    key: RecordKey,
    url: str,
) -> tuple[RecordCandidate, list[Text]] | None:
    artists = record.get("artists")
    first_artist = _object(artists[0]) if isinstance(artists, list) and artists else {}
    artist = _string(first_artist.get("name"))
    title = _string(record.get("title"))
    if not artist or not title:
        return None
    title = title.removeprefix(f"{artist} - ").strip()
    kind = EntityKind.ALBUM if record.get("type") == "ALBUM" else EntityKind.TRACK
    found_key = RecordKey(artist=artist, title=title, kind=kind)
    if compare(key, found_key).verdict is not Verdict.MATCH:
        return None
    candidate = RecordCandidate(kind=kind, artist=artist, title=title, url=url)
    provenance = Provenance(source="residentadvisor", url=url)
    scope = Scope.RELEASE_GROUP if kind is EntityKind.ALBUM else Scope.RECORDING
    texts = []
    body = _html_text(record.get("content"))
    if body:
        texts.append(
            Text(
                kind=TextKind.REVIEW,
                body=body,
                author=_string(_object(record.get("author")).get("name")),
                publication="Resident Advisor",
                date=_string(record.get("date")),
                scope=scope,
                sources=[provenance],
            ),
        )
    biography = _html_text(_object(first_artist.get("biography")).get("blurb"))
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
        label = _object(label_value)
        label_body = _html_text(label.get("blurb"))
        if label_body:
            texts.append(
                Text(
                    kind=TextKind.EDITORIAL,
                    body=label_body,
                    title=_string(label.get("name")),
                    publication="Resident Advisor",
                    scope=Scope.LABEL,
                    sources=[provenance],
                ),
            )
    return candidate, texts


class ResidentAdvisorAdapter(HttpAdapter):
    """Read linked RA reviews and associated artist and label biographies."""

    name = "residentadvisor"
    group = SourceGroup.PRESS
    pass_ = Pass.LINKS
    profile = Profile.BROWSER
    capabilities = frozenset({Capability.TEXTS})

    async def _graphql(
        self,
        operation: str,
        variables: dict[str, str],
        query: str,
    ) -> dict[str, object]:
        payload = json.dumps(
            {
                "operationName": operation,
                "variables": variables,
                "query": query,
            },
        ).encode()
        response = await self.client.request(
            "POST",
            "https://ra.co/graphql",
            headers={"content-type": "application/json"},
            body=payload,
        )
        try:
            root = _object(json.loads(response.content))
        except (ValueError, UnicodeDecodeError) as error:
            raise SourceError(
                "invalid Resident Advisor GraphQL response",
                url=response.url,
            ) from error
        if root.get("errors"):
            raise SourceError("Resident Advisor GraphQL returned errors", url=response.url)
        return _object(root.get("data"))

    async def _search_url(self, key: RecordKey) -> str | None:
        data = await self._graphql(
            "DEADWAX_SEARCH",
            {"term": f"{key.artist} {key.title}"},
            _SEARCH_QUERY,
        )
        results = data.get("search")
        for value in results if isinstance(results, list) else []:
            hit = _object(value)
            name = _string(hit.get("value"))
            path = _string(hit.get("contentUrl"))
            if not name or not path or _review_id(f"https://ra.co{path}") is None:
                continue
            artist, separator, title = name.partition(" - ")
            found_key = RecordKey(artist=artist, title=title, kind=key.kind)
            if separator and compare(key, found_key).verdict is Verdict.MATCH:
                return f"https://ra.co{path}"
        return None

    async def lookup(self, query: Query, context: LookupContext) -> Partial:
        """Query RA for a linked review and keep facts matching the record."""
        key = search_key(query, context)
        if key is None:
            raise NotFoundError("no record identity for Resident Advisor")
        links = [link.url for link in context.review_links if _review_id(link.url)]
        if not links:
            found = await self._search_url(key)
            if found is None:
                raise NotFoundError("no matching Resident Advisor review")
            links = [found]
        texts: list[Text] = []
        candidate = None
        for url in dict.fromkeys(links):
            review_id = _review_id(url)
            if review_id is None:
                continue
            record = _object(
                (await self._graphql("DEADWAX_REVIEW", {"id": review_id}, _QUERY)).get("review"),
            )
            extracted = _extract(record, key, url)
            if extracted is None:
                continue
            candidate, found_texts = extracted
            texts.extend(found_texts)
        if not texts:
            raise NotFoundError("no matching Resident Advisor review")
        return Partial(source=self.name, candidate=candidate, texts=texts)
