from collections.abc import Callable

import httpx
import pytest

from deadwax import EntityKind, HttpSettings, Query, RelationKind, SourcesConfig, lookup
from deadwax.sources.adapters.wfmu import adapter as wfmu_module


@pytest.mark.asyncio
async def test_wfmu_playlist_comment() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("artistbrowser.php"):
            if request.method == "GET":
                assert request.url.params["initial"] == "B"
                return httpx.Response(
                    200,
                    text='<button name="id" value="50807">Burial</button>',
                )
            assert request.url.params["action"] == "artist"
            assert request.content == b"id=50807"
            return httpx.Response(
                200,
                text=(
                    '<table><tr><td class="show">Burial</td>'
                    '<td class="show">Archangel '
                    "<font>(plus 0 other tracks on this show)</font></td>"
                    '<td class="show">Example</td><td class="date">'
                    '<a href="/playlists/shows/12345">Nov 15 2026</a></td></tr></table>'
                ),
            )
        return httpx.Response(
            200,
            text=(
                "<title>WFMU: Example with DJ Ada: Playlist from Nov 15 2026</title>"
                '<table><tr><td class="col_artist">'
                '<font>Burial</font></td><td class="col_song_title">'
                '<font>Archangel</font><span>→ "Archangel" by "Burial"</span></td>'
                '<td class="col_comments"><font>Host note.</font></td>'
                '<td class="col_live_timestamps_flag">2:05:40</td></tr>'
                '<tr><td class="col_artist"><font>Burial</font></td>'
                '<td class="col_song_title"><font>Archangel (Live)</font></td></tr></table>'
            ),
        )

    dossier = await lookup(
        Query(kind=EntityKind.TRACK, artist="Burial", title="Archangel"),
        SourcesConfig(http=HttpSettings(escalation=())),
        include=("wfmu",),
        transport=httpx.MockTransport(respond),
    )

    assert [relation.kind for relation in dossier.relations] == [RelationKind.BROADCAST]
    assert dossier.relations[0].target.date == "2026-11-15"
    assert [text.body for text in dossier.texts] == ["Host note."]
    assert dossier.texts[0].author == "DJ Ada"
    assert dossier.texts[0].publication == "WFMU: Example with DJ Ada"


@pytest.mark.asyncio
async def test_wfmu_returns_the_playlists_read_before_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
    traced: Callable[[str], list[dict[str, object]]],
) -> None:
    playlists: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("artistbrowser.php"):
            if request.method == "GET":
                return httpx.Response(200, text='<button name="id" value="1">Burial</button>')
            rows = "".join(
                '<tr><td class="show">Burial</td><td class="show">Archangel</td>'
                f'<td class="show">Example</td><td class="date">'
                f'<a href="/playlists/shows/{show}">Nov 15 2026</a></td></tr>'
                for show in (1, 2, 3)
            )
            return httpx.Response(200, text=f"<table>{rows}</table>")
        playlists.append(request.url.path)
        return httpx.Response(
            200,
            text=(
                "<title>WFMU: Example with DJ Ada: Playlist from Nov 15 2026</title>"
                '<table><tr><td class="col_artist"><font>Burial</font></td>'
                '<td class="col_song_title"><font>Archangel</font></td></tr></table>'
            ),
        )

    monkeypatch.setattr(wfmu_module, "adapter_time_left", lambda: 1.0)

    dossier = await lookup(
        Query(kind=EntityKind.TRACK, artist="Burial", title="Archangel"),
        SourcesConfig(http=HttpSettings(escalation=())),
        include=("wfmu",),
        transport=httpx.MockTransport(respond),
    )

    assert playlists == ["/playlists/shows/1"]
    assert len(dossier.relations) == 1
    [event] = traced("wfmu.truncated")
    assert (event["read"], event["remaining"]) == (1, 2)
