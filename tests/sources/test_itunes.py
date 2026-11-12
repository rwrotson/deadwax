import pytest

from deadwax.core import EntityKind, RecordKey
from deadwax.sources.itunes import Item, clean_url, partial, pick


def item(**fields: object) -> Item:
    return Item.model_validate({"wrapperType": "track", "artistName": "Radiohead"} | fields)


def test_clean_url() -> None:
    url = "https://music.apple.com/us/album/x/1?i=2&uo=4"

    assert clean_url(url) == "https://music.apple.com/us/album/x/1?i=2"
    assert clean_url(url, album=True) == "https://music.apple.com/us/album/x/1"


def test_pick_takes_the_earliest_matching_release() -> None:
    items = [
        item(trackName="Paranoid Android", releaseDate="2017-06-23T07:00:00Z", trackId=2),
        item(trackName="Paranoid Android", releaseDate="1997-05-21T07:00:00Z", trackId=1),
        item(trackName="Paranoid Android (Live)", releaseDate="1990-01-01T07:00:00Z", trackId=3),
        item(wrapperType="artist"),
    ]

    chosen = pick(RecordKey("Radiohead", "Paranoid Android", EntityKind.TRACK), items)

    assert chosen is not None
    assert chosen.track_id == 1


@pytest.mark.parametrize(
    ("fields", "kind"),
    [
        ({"trackName": "Paranoid Android"}, EntityKind.TRACK),
        ({"wrapperType": "collection", "collectionName": "OK Computer"}, EntityKind.ALBUM),
        ({"wrapperType": "artist"}, None),
    ],
)
def test_item_kinds(fields: dict[str, object], kind: EntityKind | None) -> None:
    assert item(**fields).kind is kind


def test_partial_without_urls_or_genre() -> None:
    found = partial(item(wrapperType="collection", collectionName="OK Computer"))

    assert found.candidate is not None
    assert found.candidate.kind is EntityKind.ALBUM
    assert found.candidate.ids == {}
    assert found.links == []
    assert found.tags == []
