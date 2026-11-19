import httpx
import pytest

from deadwax import EntityKind, HttpSettings, LookupConfig, Query, RelationKind, lookup

EPISODE = "https://www.nts.live/shows/example/episodes/example-2026"


@pytest.mark.asyncio
async def test_nts_episode_has_context_genre_and_neighbours() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/search":
            assert request.url.params["version"] == "2"
            assert request.url.params["types[]"] == "track"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Archangel (Live)",
                            "artists": [{"name": "Burial"}],
                            "article": {"path": "/shows/wrong/episodes/live"},
                        },
                        {
                            "title": "Archangel",
                            "artists": [{"name": "Burial"}],
                            "article": {"path": "/shows/example/episodes/example-2026"},
                        },
                    ],
                },
            )
        assert str(request.url) == "https://www.nts.live/api/v2/shows/example/episodes/example-2026"
        return httpx.Response(
            200,
            json={
                "name": "Example",
                "date": "2026-11-15",
                "broadcast": "2026-11-15T20:00:00+00:00",
                "genres": [{"value": "Electronic"}],
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
        LookupConfig(http=HttpSettings(escalation=())),
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
    assert dossier.relations[0].target.date == "2026-11-15"
