import json
from collections.abc import Callable

import httpx
import pytest

from deadwax.core import (
    EntityKind,
    ExternalId,
    Identity,
    IdKind,
    LookupContext,
    NotFoundError,
    Provenance,
    Query,
    Scope,
    TextKind,
    parse_query,
)
from deadwax.sources import SourcesConfig
from deadwax.sources._http import HttpResources
from deadwax.sources.wikipedia import WikipediaAdapter

type Handler = Callable[[httpx.Request], object]


def ref(prop: str, qid: str) -> dict[str, object]:
    value = {"type": "wikibase-entityid", "value": {"id": qid}}
    return {"mainsnak": {"property": prop, "datavalue": value}}


def labels(**by_language: str) -> dict[str, dict[str, str]]:
    return {lang: {"language": lang, "value": value} for lang, value in by_language.items()}


def sitelink(site: str, title: str) -> dict[str, str]:
    return {"site": site, "title": title}


SONG = {
    "id": "Q1",
    "labels": labels(ru="Песня", en="Pesnya"),
    "claims": {
        "P31": [ref("P31", "Q7366")],
        "P175": [ref("P175", "Q10")],
        "P136": [ref("P136", "Q20")],
        "P361": [ref("P361", "Q50")],
        "P407": [ref("P407", "Q7737")],
    },
    "sitelinks": {
        "ruwiki": sitelink("ruwiki", "Песня"),
        "enwiki": sitelink("enwiki", "Pesnya (song)"),
    },
}
ALBUM = {
    "id": "Q50",
    "labels": labels(en="Record"),
    "claims": {"P31": [ref("P31", "Q482994")], "P175": [ref("P175", "Q10")]},
    "sitelinks": {"enwiki": sitelink("enwiki", "Record")},
}
REFERENCED = {
    "Q10": {"id": "Q10", "labels": labels(ru="Группа", en="Gruppa")},
    "Q20": {"id": "Q20", "labels": labels(en="post-punk")},
    "Q50": {"id": "Q50", "labels": labels(en="Record")},
    "Q7737": {"id": "Q7737", "labels": labels(en="Russian")},
}
RU_PAGE = {
    "title": "Песня",
    "text": '<div class="mw-parser-output"><p>Вступление.</p>'
    '<div class="mw-heading mw-heading2"><h2 id="x">История песни</h2></div><p>История.</p></div>',
    "wikitext": "{{Рейтинги альбома|rev1=Критик|rev1Score=(положительная)}}",
}
EN_ALBUM_PAGE = {
    "title": "Record",
    "text": "<p>About the record.</p>",
    "wikitext": "{{Album ratings|rev1=[[AllMusic]]|rev1score={{Rating|4|5}}}}",
}


def wikidata(request: httpx.Request) -> object:
    params = request.url.params
    action = params["action"]
    if action == "wbgetclaims":
        return {"claims": {"P424": [{"mainsnak": {"property": "P424", "datavalue": {
            "type": "string", "value": "ru"}}}]}}  # fmt: skip
    if action == "query":
        return {"query": {"search": [{"title": "Q99"}, {"title": "Q1"}]}}
    ids = params["ids"].split("|")
    every = {"Q1": SONG, "Q50": ALBUM, "Q99": {"id": "Q99", "labels": labels(en="Pesnya")}}
    if params["props"] == "claims":
        return {"entities": {qid: {"id": qid, "claims": ALBUM["claims"]} for qid in ids}}
    if "sitelinks" in params["props"] or "claims" in params["props"]:
        return {"entities": {qid: every.get(qid, {"id": qid, "missing": ""}) for qid in ids}}
    return {"entities": {qid: REFERENCED.get(qid, {"id": qid}) for qid in ids}}


def articles(request: httpx.Request) -> object:
    page = request.url.params["page"]
    host = request.url.host
    if host == "ru.wikipedia.org" and page == "Песня":
        return {"parse": RU_PAGE}
    if host == "en.wikipedia.org" and page == "Pesnya (song)":
        # The song's English sitelink redirects to the album article.
        return {"parse": EN_ALBUM_PAGE}
    if host == "en.wikipedia.org" and page == "Record":
        return {"parse": EN_ALBUM_PAGE}
    return {"error": {"code": "missingtitle", "info": "The page does not exist."}}


def make(seen: list[httpx.Request] | None = None, **overrides: Handler) -> WikipediaAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        route = "wikidata" if request.url.host == "www.wikidata.org" else "articles"
        body = overrides.get(route, {"wikidata": wikidata, "articles": articles}[route])(request)
        return httpx.Response(200, content=json.dumps(body).encode())

    config = SourcesConfig.model_validate(
        {"wikipedia": {"rate": 1000}, "http": {"retries": 0, "escalation": "none"}}
    )
    return WikipediaAdapter(config, HttpResources(transport=httpx.MockTransport(handler)))


def with_qid(query: Query, qid: str) -> LookupContext:
    ids = [ExternalId(kind=IdKind.WIKIDATA, value=qid, sources=[Provenance(source="musicbrainz")])]
    return LookupContext(query=query, identity=Identity(external_ids=ids))


TRACK = parse_query("Группа - Песня", EntityKind.TRACK)


@pytest.mark.asyncio
async def test_song_from_an_earlier_pass_with_its_russian_article() -> None:
    seen: list[httpx.Request] = []
    adapter = make(seen)

    partial = await adapter.lookup(TRACK, with_qid(TRACK, "Q1"))
    await adapter.aclose()

    assert partial.candidate is not None
    assert (partial.candidate.artist, partial.candidate.title) == ("Группа", "Песня")
    assert [t.name for t in partial.tags] == ["post-punk"]
    assert [(r.target.name, r.scope) for r in partial.relations] == [("Record", Scope.RECORDING)]
    assert [(t.kind, t.language, t.title, t.body) for t in partial.texts] == [
        (TextKind.WIKI, "ru", "Песня", "Вступление."),
        (TextKind.WIKI, "ru", "История песни", "История."),
        (TextKind.REVIEW, "ru", None, ""),
    ]
    assert partial.texts[1].sources[0].url == (
        "https://ru.wikipedia.org/wiki/%D0%9F%D0%B5%D1%81%D0%BD%D1%8F#x"
    )
    hosts = [request.url.host for request in seen]
    assert hosts.count("en.wikipedia.org") == 1


@pytest.mark.asyncio
async def test_kind_of_a_url_query_comes_from_the_item() -> None:
    query = parse_query("https://example.com/record")

    partial = await make().lookup(query, with_qid(query, "Q50"))

    assert partial.candidate is not None
    assert partial.candidate.kind is EntityKind.ALBUM
    assert [(t.publication, t.scope) for t in partial.texts if t.kind is TextKind.REVIEW] == [
        ("AllMusic", Scope.RELEASE_GROUP)
    ]


@pytest.mark.asyncio
async def test_track_found_by_search() -> None:
    seen: list[httpx.Request] = []

    partial = await make(seen).lookup(TRACK, LookupContext(query=TRACK))

    assert partial.candidate is not None
    assert partial.candidate.ids[IdKind.WIKIDATA] == "Q1"
    search = next(r for r in seen if r.url.params.get("action") == "query")
    assert search.url.params["srsearch"].startswith("Песня haswbstatement:P31=")


@pytest.mark.asyncio
async def test_search_without_kind_or_results() -> None:
    query = parse_query("https://example.com/x")
    identity = Identity.model_validate(
        {"artist": {"value": "Группа", "sources": []}, "title": {"value": "Песня", "sources": []}}
    )
    seen: list[httpx.Request] = []

    partial = await make(seen).lookup(query, LookupContext(query=query, identity=identity))

    assert partial.candidate is not None
    search = next(r for r in seen if r.url.params.get("action") == "query")
    assert search.url.params["srsearch"] == "Песня"
    empty = make(wikidata=lambda r: {"query": {"search": []}})
    with pytest.raises(NotFoundError, match="no Wikidata item"):
        await empty.lookup(TRACK, LookupContext(query=TRACK))


@pytest.mark.asyncio
async def test_search_without_a_match() -> None:
    other = parse_query("Somebody - Песня", EntityKind.TRACK)

    with pytest.raises(NotFoundError, match="no matching"):
        await make().lookup(other, LookupContext(query=other))


@pytest.mark.asyncio
async def test_nothing_to_look_up() -> None:
    query = parse_query("https://example.com/x")

    with pytest.raises(NotFoundError):
        await make().lookup(query, LookupContext(query=query))


@pytest.mark.asyncio
async def test_missing_item() -> None:
    with pytest.raises(NotFoundError, match="no such Wikidata item"):
        await make().lookup(TRACK, with_qid(TRACK, "Q404"))


@pytest.mark.asyncio
async def test_many_referenced_items_are_fetched_in_batches() -> None:
    genres = [ref("P136", f"Q{1000 + n}") for n in range(60)]
    song = SONG | {"claims": {**SONG["claims"], "P136": genres}}  # type: ignore[dict-item]
    seen: list[httpx.Request] = []

    def items(request: httpx.Request) -> object:
        if request.url.params.get("ids") == "Q1":
            return {"entities": {"Q1": song}}
        return wikidata(request)

    await make(seen, wikidata=items).lookup(TRACK, with_qid(TRACK, "Q1"))

    label_requests = [r for r in seen if r.url.params.get("props") == "labels|aliases"]
    assert len(label_requests) == 2


@pytest.mark.asyncio
async def test_missing_article_is_skipped() -> None:
    gone = SONG | {"sitelinks": {"ruwiki": sitelink("ruwiki", "Удалённая статья")}}

    def items(request: httpx.Request) -> object:
        if request.url.params.get("ids") == "Q1":
            return {"entities": {"Q1": gone}}
        return wikidata(request)

    partial = await make(wikidata=items).lookup(TRACK, with_qid(TRACK, "Q1"))

    assert partial.texts == []
    assert partial.candidate is not None
