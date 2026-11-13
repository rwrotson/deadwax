from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, model_validator


def _as_list(value: object) -> list[Any]:
    """Accept one object where search results give a list, and the reverse."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    # Search results name fields after their entity ('track_name'); catalogue pages do not.
    renames: ClassVar[dict[str, str]] = {}
    lists: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def _catalogue_names(cls, data: Any) -> Any:  # noqa: ANN401 -- raw input of any shape
        if not isinstance(data, dict):
            return data
        renamed = {cls.renames.get(name, name): value for name, value in data.items()}
        for name in cls.lists & renamed.keys():
            renamed[name] = _as_list(renamed[name])
        return renamed


class Named(_Model):
    """Artist, genre, or label."""

    renames = {
        "artist_id": "id",
        "genre_id": "id",
        "label_id": "id",
        "artist_name": "name",
        "genre_name": "name",
        "label_name": "name",
    }

    id: int | None = None
    name: str
    slug: str | None = None


class Key(_Model):
    """Musical key of a track."""

    name: str


class ReleaseRef(_Model):
    """Release a track appears on."""

    renames = {"release_id": "id", "release_name": "name"}

    id: int | None = None
    name: str | None = None
    slug: str | None = None
    catalog_number: str | None = None
    label: Named | None = None


class Track(_Model):
    """Track of the catalogue (track pages) or of search results."""

    renames = {
        "track_id": "id",
        "track_name": "name",
        "key_name": "key",
        "genre": "genres",
        "sub_genre": "sub_genres",
    }
    lists = frozenset({"genres", "sub_genres", "artists", "remixers"})

    id: int
    name: str
    mix_name: str | None = None
    slug: str | None = None
    bpm: float | None = None
    key: Key | None = None
    isrc: str | None = None
    genres: list[Named] = []
    sub_genres: list[Named] = []
    artists: list[Named] = []
    remixers: list[Named] = []
    release: ReleaseRef | None = None
    label: Named | None = None
    publish_date: str | None = None
    new_release_date: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _key_name(cls, data: Any) -> Any:  # noqa: ANN401 -- raw input of any shape
        """Search results give the key as a bare name."""
        if not isinstance(data, dict):
            return data
        return {
            name: {"name": value}
            if name in {"key", "key_name"} and isinstance(value, str)
            else value
            for name, value in data.items()
        }


class Release(_Model):
    """Release of the catalogue (release pages) or of search results."""

    renames = {"release_id": "id", "release_name": "name", "genre": "genres"}
    lists = frozenset({"genres", "artists", "remixers"})

    id: int
    name: str
    slug: str | None = None
    catalog_number: str | None = None
    upc: str | None = None
    label: Named | None = None
    artists: list[Named] = []
    remixers: list[Named] = []
    genres: list[Named] = []
    publish_date: str | None = None
    new_release_date: str | None = None
