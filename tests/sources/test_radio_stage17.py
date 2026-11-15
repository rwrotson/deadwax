import httpx
import pytest

from deadwax import EntityKind, HttpSettings, Query, RelationKind, SourcesConfig, lookup

EPISODE = "https://www.nts.live/shows/example/episodes/example-2026"
PLAYLIST = "https://wfmu.org/playlists/shows/12345"


@pytest.mark.asyncio
async def test_nts_episode_has_context_genre_and_neighbours() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/search":
            return httpx.Response(200, json={"results": [{"episode": {"url": EPISODE}}]})
        return httpx.Response(
            200,
            json={
                "name": "Example",
                "date": "2026-11-15",
                "genres": [{"name": "Electronic"}],
                "embeds": {
                    "tracklist": {
                        "results": [
                            {"artist": "A", "title": "Before"},
                            {"artist": "Burial", "title": "Archangel"},
                            {"artist": "B", "title": "After"},
                        ],
                    },
                },
            },
        )

    dossier = await lookup(
        Query(kind=EntityKind.TRACK, artist="Burial", title="Archangel"),
        SourcesConfig(http=HttpSettings(escalation=())),
        include=("nts",),
        transport=httpx.MockTransport(respond),
    )

    assert {relation.kind for relation in dossier.relations} == {
        RelationKind.BROADCAST,
        RelationKind.CO_PLAYED,
    }
    assert {
        relation.note for relation in dossier.relations if relation.kind is RelationKind.CO_PLAYED
    } == {
        "before",
        "after",
    }
    assert [(tag.name, tag.context_url) for tag in dossier.tags] == [("Electronic", EPISODE)]


@pytest.mark.asyncio
async def test_wfmu_playlist_comment() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("searchadv.php"):
            return httpx.Response(200, text=f'<a href="{PLAYLIST}">Playlist</a>')
        return httpx.Response(
            200,
            text=(
                "<title>WFMU: Example</title><table><tr><td>Burial</td>"
                "<td>Archangel</td><td>Host note.</td></tr></table>"
            ),
        )

    dossier = await lookup(
        Query(kind=EntityKind.TRACK, artist="Burial", title="Archangel"),
        SourcesConfig(http=HttpSettings(escalation=())),
        include=("wfmu",),
        transport=httpx.MockTransport(respond),
    )

    assert [relation.kind for relation in dossier.relations] == [RelationKind.BROADCAST]
    assert [text.body for text in dossier.texts] == ["Host note."]
