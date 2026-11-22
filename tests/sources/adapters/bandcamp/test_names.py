import html
import json
from collections.abc import Callable

import httpx
import pytest

from deadwax import EntityKind, ErrorKind, IdKind, LinkTarget, LookupConfig, RelationKind, lookup
from deadwax.cli.markdown import to_markdown
from deadwax.core import ArtistIdentity, Capability, LabelIdentity, Query, Request, UnresolvedQuery
from deadwax.sources import parse_query

ROOT = "https://band.bandcamp.com/"
MUSIC = f"{ROOT}music"
Replay = Callable[..., httpx.MockTransport]


@pytest.mark.parametrize(
    "account",
    [
        (
            "bandcamp_artist_search",
            "Aphex Twin",
            EntityKind.ARTIST,
            "Aphex Twin",
            "aphextwin",
            "UK",
        ),
        (
            "bandcamp_label_search",
            "Hyperdub",
            EntityKind.LABEL,
            "Hyperdub",
            "hyperdub",
            "London, UK",
        ),
        (
            "bandcamp_artist_url",
            "https://burial.bandcamp.com/",
            None,
            "Burial",
            "burial",
            "London, UK",
        ),
        (
            "bandcamp_label_url",
            "https://warprecords.bandcamp.com/",
            None,
            "Warp Records",
            "warprecords",
            "London, UK",
        ),
    ],
)
@pytest.mark.asyncio
async def test_account_routes(
    account: tuple[str, str, EntityKind | None, str, str, str],
    replay: Replay,
    config: LookupConfig,
) -> None:
    scenario, text, kind, name, host, location = account
    url = f"https://{host}.bandcamp.com"
    seen: list[str] = []
    query = parse_query(text, kind)
    if kind is None:
        assert isinstance(query, UnresolvedQuery)
    dossier = await lookup(query, config, include=("bandcamp",), transport=replay(scenario, seen))

    identity = dossier.identity
    is_label = name in {"Hyperdub", "Warp Records"}
    assert isinstance(identity, LabelIdentity if is_label else ArtistIdentity)
    assert not dossier.errors
    assert identity.name is not None
    assert identity.name.value == name
    assert identity.location is not None
    assert identity.location.value == location
    assert identity.location.sources[0].url == f"{url}/music"
    assert identity.external_ids[0].kind is IdKind.BANDCAMP_ACCOUNT
    assert identity.external_ids[0].value == f"{host}.bandcamp.com"
    assert dossier.links[0].url == f"{url}/"
    assert dossier.links[0].target is (LinkTarget.LABEL if is_label else LinkTarget.ARTIST)
    assert dossier.relations
    assert all(
        r.kind is (RelationKind.LABEL_RELEASE if is_label else RelationKind.RELEASE)
        for r in dossier.relations
    )
    assert all(
        source.source == "bandcamp" and source.url == f"{url}/music"
        for fact in [*dossier.links, *dossier.relations, *dossier.texts]
        for source in fact.sources
    )
    if name in {"Hyperdub", "Burial"}:
        assert dossier.texts[0].title == "Profile"
    assert any(request.startswith("POST ") for request in seen) is (kind is not None)
    assert location in to_markdown(dossier)


@pytest.mark.parametrize(
    ("scenario", "query", "host"),
    [
        ("aphex_twin", parse_query("Aphex Twin", EntityKind.ARTIST), "aphextwin"),
        ("warp", parse_query("Warp", EntityKind.LABEL), "warprecords"),
    ],
)
@pytest.mark.asyncio
async def test_musicbrainz_account_link(
    scenario: str,
    query: Query,
    host: str,
    replay: Replay,
    config: LookupConfig,
) -> None:
    seen: list[str] = []
    dossier = await lookup(
        query,
        config,
        include=("musicbrainz", "bandcamp"),
        transport=replay(scenario, seen),
    )

    assert not dossier.errors
    assert dossier.identity.kind is query.kind
    assert [request for request in seen if "bandcamp.com" in request] == [
        f"GET https://{host}.bandcamp.com/music",
    ]
    account = next(i for i in dossier.identity.external_ids if i.kind is IdKind.BANDCAMP_ACCOUNT)
    assert {s.source for s in account.sources} == {"musicbrainz", "bandcamp"}
    assert any(s.source == "bandcamp" for r in dossier.relations for s in r.sources)


def account_html(**data: object) -> str:
    band = html.escape(json.dumps({"name": "Band", "id": 7} | data))
    return f'<div data-band="{band}"></div>'


@pytest.mark.parametrize(
    ("requested", "marker"),
    [(None, None), (None, "false"), (EntityKind.ARTIST, True)],
)
@pytest.mark.asyncio
async def test_account_requires_a_compatible_boolean_marker(
    requested: EntityKind | None,
    marker: object,
    config: LookupConfig,
) -> None:
    body = account_html() if marker is None else account_html(is_label=marker)
    dossier = await lookup(
        parse_query(ROOT, requested),
        config,
        include=("bandcamp",),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body)),
    )
    assert dossier.identity.kind is requested
    assert not dossier.identity.found
    assert [error.kind for error in dossier.errors] == [ErrorKind.NOT_FOUND]


@pytest.mark.asyncio
async def test_search_skips_wrong_kind_and_checks_the_selected_account_id(
    config: LookupConfig,
) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert json.loads(request.content)["search_filter"] == "b"
            base = {"type": "b", "name": "Band", "item_url_root": ROOT, "id": 99}
            hits = [
                base | {"is_label": True, "item_url_root": "https://label.bandcamp.com/"},
                base | {"is_label": False},
            ]
            return httpx.Response(200, json={"auto": {"results": hits}})
        assert str(request.url) == MUSIC
        return httpx.Response(200, text=account_html(is_label=False))

    dossier = await lookup(
        parse_query("Band", EntityKind.ARTIST),
        config,
        include=("bandcamp",),
        transport=httpx.MockTransport(response),
    )
    assert not dossier.identity.found
    assert [error.kind for error in dossier.errors] == [ErrorKind.NOT_FOUND]


@pytest.mark.asyncio
async def test_empty_account_search_does_not_fetch_a_page(config: LookupConfig) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, json={"auto": {"results": []}})

    dossier = await lookup(
        parse_query("Band", EntityKind.ARTIST),
        config,
        include=("bandcamp",),
        transport=httpx.MockTransport(response),
    )
    assert not dossier.identity.found
    assert [error.kind for error in dossier.errors] == [ErrorKind.NOT_FOUND]


@pytest.mark.asyncio
async def test_catalog_cap_and_facets_with_root_fallback(config: LookupConfig) -> None:
    def item(number: int, kind: str = "album") -> str:
        return (
            f'<li class="music-grid-item" data-item-id="{kind}-{number}">'
            f'<a href="/{kind}/{number}"><p class="title">Entry {number}</p></a></li>'
        )

    grid = item(99, "track") + item(1) + "".join(item(i) for i in range(1, 15))
    body = (
        account_html(is_label=False)
        + grid
        + '<div id="bio-container"><div class="signed-out-artists-bio-text">Bio</div></div>'
    )
    seen = []

    def response(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == MUSIC:
            return httpx.Response(404)
        assert str(request.url) == ROOT
        return httpx.Response(200, text=body)

    request = Request(query=parse_query(f"{ROOT}music"), facets=frozenset({Capability.RELATIONS}))
    dossier = await lookup(
        request,
        config,
        include=("bandcamp",),
        transport=httpx.MockTransport(response),
    )
    assert not dossier.errors
    assert seen == [MUSIC, ROOT]
    expected = {f"Entry {i}" for i in range(1, 13)}
    assert {r.target.name for r in dossier.relations} == expected
    assert len(dossier.relations) == len(expected)
    assert not dossier.texts
    assert not dossier.links
