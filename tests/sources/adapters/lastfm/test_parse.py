import pytest

from deadwax.core import NotFoundError, RateLimitedError, Scope, SourceError, TextKind
from deadwax.sources.adapters.lastfm import models
from deadwax.sources.adapters.lastfm import parse as p

URL = "https://www.last.fm/music/Band/_/Song"
CONTENT = (
    'First <b>paragraph</b>.\n\nSecond &amp; last. <a href="https://www.last.fm/music/Band">'
    "Read more on Last.fm</a>. User-contributed text is available under the Creative Commons "
    "By-SA License; additional terms may apply."
)


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (b'{"error": 6, "message": "Track not found"}', NotFoundError),
        (b'{"error": 29, "message": ""}', RateLimitedError),
        (b'{"error": 10, "message": "Invalid API key"}', SourceError),
    ],
)
def test_errors_in_the_body(body: bytes, error: type[SourceError]) -> None:
    with pytest.raises(error):
        p.check(body, URL)


def test_body_without_error_passes() -> None:
    p.check(b'{"track": {}}', URL)


def test_tags_have_weights_and_unused_ones_are_dropped() -> None:
    found = models.TopTags.model_validate(
        {"tag": [{"name": " electronic ", "count": 100}, {"name": "x", "count": 0},
                 {"name": "ambient", "count": "40"}, {"name": " ", "count": 5}]},
    )  # fmt: skip

    tags = p.tags(found.tag, Scope.RECORDING, URL, limit=5)

    assert [(t.name, t.weight) for t in tags] == [("electronic", 1.0), ("ambient", 0.4)]
    assert tags[0].sources[0].url == URL


@pytest.mark.parametrize(
    ("raw", "names"),
    [("", []), ({"name": "one", "count": 1}, ["one"]), ([{"name": "a", "count": 2}], ["a"])],
)
def test_single_and_empty_lists(raw: object, names: list[str]) -> None:
    assert [t.name for t in models.TopTags.model_validate({"tag": raw}).tag] == names


def test_empty_containers() -> None:
    assert models.TopTagsResponse.model_validate({"toptags": ""}).toptags.tag == []
    similar = models.SimilarArtistsResponse.model_validate({"similarartists": {"artist": ""}})
    assert similar.similar.artist == []


def test_wiki_text_is_cleaned() -> None:
    wiki = models.Wiki(published="01 Jan 2009, 12:00", summary="short", content=CONTENT)

    [text] = p.wiki_texts(wiki, Scope.RECORDING, URL)

    assert text.body == "First paragraph.\n\nSecond & last."
    assert (text.kind, text.publication, text.date) == (TextKind.WIKI, "Last.fm", "2009-01-01")


def test_summary_when_there_is_no_content() -> None:
    wiki = models.Wiki(published="soon", summary="Only a summary.")

    [text] = p.wiki_texts(wiki, Scope.RELEASE_GROUP, URL)

    assert (text.body, text.date) == ("Only a summary.", None)


def test_no_wiki() -> None:
    assert p.wiki_texts(None, Scope.RECORDING, URL) == []
    link_only = models.Wiki(summary=' <a href="x">Read more on Last.fm</a>')
    assert p.wiki_texts(link_only, Scope.RECORDING, URL) == []
    assert p.published(None) is None


def test_similar_items() -> None:
    tracks = models.SimilarTracks.model_validate(
        {"track": {"name": "Other", "match": "0.5", "url": "u", "artist": {"name": "B"}}},
    )
    artists = models.SimilarArtists.model_validate({"artist": [{"name": "C"}]})

    [track] = p.similar_tracks(tracks.track, URL)
    [artist] = p.similar_artists(artists.artist, None)

    assert (track.target.name, track.target.artist, track.note) == ("Other", "B", "match 0.50")
    assert (artist.target.name, artist.note, artist.scope) == ("C", None, Scope.ARTIST)
