import json
from collections.abc import Callable

import pytest

from deadwax.core import (
    Entity,
    EntityKind,
    EntityType,
    IdKind,
    Provenance,
    RecordKey,
    RelationKind,
    Scope,
    TextKind,
)
from deadwax.sources.bandcamp import models
from deadwax.sources.bandcamp import parse as p

ALBUM_URL = (
    "https://brianleeds.bandcamp.com/album/for-those-of-you-who-have-never-and-also-those-who-have"
)
SOURCES = [Provenance(source="bandcamp")]

Recorded = Callable[[str, str], bytes]


@pytest.fixture
def album(recorded: Recorded) -> p.Record:
    record = p.page_record(p.read_page(recorded("huerco_s", f"GET {ALBUM_URL}"), ALBUM_URL))
    assert record is not None
    return record


def test_album_page(album: p.Record) -> None:
    record = album

    assert (record.kind, record.artist, record.date) == (
        EntityKind.ALBUM,
        "Huerco S.",
        "2016-06-20",
    )
    assert (record.id, record.band_id) == (3201218634, 1046469632)
    assert record.seller_url == "https://brianleeds.bandcamp.com"
    assert "ambient" in record.tags
    assert len(record.tracks) == 9
    assert record.comments
    assert record.recommendations[0].kind is RelationKind.SIMILAR


def test_track_page_names_its_album(recorded: Recorded) -> None:
    url = "https://radiohead.bandcamp.com/track/paranoid-android"

    record = p.page_record(p.read_page(recorded("paranoid_android", f"GET {url}"), url))

    assert record is not None
    assert record.kind is EntityKind.TRACK
    assert record.album is not None
    assert record.album.url == "https://radiohead.bandcamp.com/album/ok-computer"
    assert not p.on_compilation(record)


def test_page_without_data() -> None:
    assert p.page_record(p.read_page(b"<html></html>", "https://x.bandcamp.com/album/a")) is None
    assert not p.read_page(b"<html></html>", "https://x.bandcamp.com/album/a").found


def test_json_ld_only_page() -> None:
    page = (
        '<script type="application/ld+json">{"@type": "MusicRecording", "name": "Song",'
        ' "byArtist": {"name": "Band"}, "datePublished": "01 Feb 2020 00:00:00 GMT",'
        ' "keywords": "ambient, drone", "@id": "https://b.bandcamp.com/track/song?from=x",'
        ' "comment": [{"text": "Lovely", "author": {"name": "fan"}}, "junk",'
        ' {"text": ["", " "]}]}</script>'
        '<div data-tralbum="{&quot;broken&quot;: true}"></div>'
        '<div data-embed="{&quot;artist&quot;: &quot;Embed Artist&quot;}"></div>'
    )

    record = p.page_record(p.read_page(page.encode(), "https://b.bandcamp.com/track/song"))

    assert record is not None
    assert (record.kind, record.title, record.date) == (EntityKind.TRACK, "Song", "2020-02-01")
    assert record.artist == "Embed Artist"
    assert record.url == "https://b.bandcamp.com/track/song"
    assert record.tags == ("ambient", "drone")
    assert [(c.author, c.body) for c in record.comments] == [("fan", "Lovely")]


def test_page_without_artist() -> None:
    page = b'<script type="application/ld+json">{"@type": "MusicAlbum", "name": "A"}</script>'

    assert p.page_record(p.read_page(page, "https://b.bandcamp.com/album/a")) is None


def test_dates() -> None:
    assert p.page_date("20 Jun 2016 00:00:00 GMT") == "2016-06-20"
    assert p.page_date("June 2016") is None
    assert p.page_date(None) is None
    assert p.unix_date(1466380800) == "2016-06-20"
    assert p.unix_date(None) is None


def test_credit_lines() -> None:
    text = (
        "Mastered by Simon Davey\r\n"
        "Written and produced by A & B\n"
        "Mixed, recorded by C.\n"
        "Released on Proibito\n"
        "Sung by D"
    )

    people = p.credit_lines(text, Scope.RELEASE, SOURCES)

    assert [(c.role, c.name) for c in people] == [
        ("mastering", "Simon Davey"),
        ("writer", "A"),
        ("writer", "B"),
        ("producer", "A"),
        ("producer", "B"),
        ("mix", "C"),
        ("recording", "C"),
    ]
    assert p.credit_lines(None, Scope.RELEASE, SOURCES) == []


def test_mobile_details(recorded: Recorded, album: p.Record) -> None:
    details = models.MobileDetails.model_validate_json(
        recorded(
            "huerco_s",
            "GET https://bandcamp.com/api/mobile/24/tralbum_details"
            "?band_id=1046469632&tralbum_id=3201218634&tralbum_type=a",
        )
    )

    record = p.details_record(details)
    enriched = p.with_details(album, details)

    assert (record.kind, record.artist, record.label) == (
        EntityKind.ALBUM,
        "Huerco S.",
        "West Mineral Ltd.",
    )
    assert record.seller_url == "https://brianleeds.bandcamp.com"
    assert "Philadelphia" not in record.tags
    assert enriched.label == "West Mineral Ltd."
    assert "Philadelphia" not in enriched.tags


def test_details_of_a_track_without_url() -> None:
    details = models.MobileDetails(id=1, type="t", title="T", band=models.MobileBand(name="B"))

    record = p.details_record(details)

    assert (record.kind, record.artist, record.seller_url) == (EntityKind.TRACK, "B", None)


def test_partial_of_an_album(album: p.Record) -> None:
    record = p.with_details(
        album,
        models.MobileDetails(id=1, type="a", title="x", label="Label", about="Notes"),
    )

    partial = p.partial(p._replace(record, about="About text"), [])

    assert partial.candidate is not None
    assert partial.candidate.ids == {IdKind.BANDCAMP_ALBUM: "3201218634"}
    assert {t.title for t in partial.texts if t.kind is TextKind.LABEL} == {"About", "Credits"}
    assert RelationKind.LABEL in {r.kind for r in partial.relations}
    assert all(r.sources for r in partial.relations)


def test_compilation_track_keeps_only_its_own_facts() -> None:
    record = p.Record(
        kind=EntityKind.TRACK,
        artist="Everything but the Girl",
        title="Missing",
        url="https://c.bandcamp.com/track/missing",
        date="2007-01-01",
        label="Comp Label",
        seller="Comp",
        seller_url="https://c.bandcamp.com",
        album=Entity(type=EntityType.RELEASE, name="Comp", artist="Jay Burnett", url="https://c"),
        tags=("ballroom",),
        credits="Remixed by Todd Terry",
    )

    partial = p.partial(record)

    assert p.on_compilation(record)
    assert partial.tags == []
    assert partial.candidate is not None
    assert partial.candidate.date is None
    assert partial.candidate.labels == []
    assert [r.kind for r in partial.relations] == [RelationKind.COMPILATION]
    assert [(c.role, c.name) for c in partial.credits] == [("remixer", "Todd Terry")]


def test_search_results() -> None:
    reference = RecordKey("Huerco S.", "For Those of You Who Have Never", EntityKind.ALBUM)
    results = [
        models.SearchResult(type="t", id=1, name="For Those of You Who Have Never",
                            band_name="Huerco S.", item_url_path="https://x/track/a"),
        models.SearchResult(type="a", id=2, name="Other", band_name="Huerco S.",
                            item_url_path="https://x/album/b"),
        models.SearchResult(type="a", id=3, name="For Those of You Who Have Never",
                            band_name="Huerco S.", item_url_path="https://x/album/c"),
    ]  # fmt: skip

    found = p.pick_result(reference, results)

    assert found is not None
    assert found.id == 3


def test_html_search() -> None:
    page = b"""
    <ul>
      <li class="searchresult data-search"><div class="itemtype">ALBUM</div>
        <div class="heading"><a href="https://a.bandcamp.com/album/x?from=search">Album X</a></div>
        <div class="subhead">by Artist A</div>
        <div class="itemurl"><a href="https://a.bandcamp.com/album/x?from=search">a</a></div></li>
      <li class="searchresult data-search"><div class="itemtype">TRACK</div>
        <div class="heading"><a href="https://a.bandcamp.com/track/y">Track Y</a></div>
        <div class="subhead">from Album X by Artist A</div></li>
      <li class="searchresult data-search"><div class="itemtype">ARTIST</div>
        <div class="heading"><a href="https://a.bandcamp.com">Artist A</a></div></li>
    </ul>
    """

    results = p.html_search(page)

    assert [(r.type, r.name, r.band_name, r.item_url_path) for r in results] == [
        ("a", "Album X", "Artist A", "https://a.bandcamp.com/album/x"),
        ("t", "Track Y", "Artist A", "https://a.bandcamp.com/track/y"),
    ]


def test_track_url_on_an_album(album: p.Record) -> None:
    record = album

    found = p.track_url(record, RecordKey("Huerco S.", "A Sea of Love", EntityKind.TRACK))
    missing = p.track_url(record, RecordKey("Huerco S.", "Not There", EntityKind.TRACK))

    assert found == "https://brianleeds.bandcamp.com/track/a-sea-of-love"
    assert missing is None


def test_label_releases() -> None:
    page = b"""
    <ol>
      <li class="music-grid-item" data-item-id="album-1"><a href="/album/one">
        <p class="title">One <br><span class="artist-override">Someone</span></p></a></li>
      <li class="music-grid-item" data-item-id="album-2"><a href="/album/self">
        <p class="title">Self</p></a></li>
      <li class="music-grid-item" data-item-id="track-3"><a href="/track/three">
        <p class="title">Three</p></a></li>
      <li class="music-grid-item" data-item-id="album-4"><p class="title">No link</p></li>
    </ol>
    """

    relations = p.label_releases(page, "https://label.bandcamp.com/music", "Label", 2)

    assert [(r.target.name, r.target.artist, r.target.url, r.target.ids) for r in relations] == [
        ("One", "Someone", "https://label.bandcamp.com/album/one", {IdKind.BANDCAMP_ALBUM: "1"}),
        ("Three", "Label", "https://label.bandcamp.com/track/three", {}),
    ]


def test_label_releases_are_limited() -> None:
    item = '<li class="music-grid-item" data-item-id="album-{0}"><a href="/a/{0}">'
    item += '<p class="title">R{0}</p></a></li>'
    page = "".join(item.format(n) for n in range(30)).encode()

    relations = p.label_releases(page, "https://l.bandcamp.com/music", "L", None)

    assert len(relations) == p.LABEL_RELEASES_LIMIT


def test_same_name() -> None:
    assert p.same_name("ILIAN TAPE", "Ilian Tape")
    assert not p.same_name("Proibito", None)


def test_keywords_and_names_of_odd_shapes() -> None:
    page = {
        "@type": "MusicAlbum",
        "name": "A",
        "byArtist": "not an object",
        "keywords": 5,
        "publisher": "x",
        "inAlbum": {"name": None},
    }
    html = f'<script type="application/ld+json">{json.dumps(page)}</script>'
    html += '<div data-embed="{&quot;artist&quot;: &quot;E&quot;}"></div>'

    record = p.page_record(p.read_page(html.encode(), "https://e.bandcamp.com/album/a"))

    assert record is not None
    assert (record.artist, record.tags, record.seller_url) == ("E", (), None)
