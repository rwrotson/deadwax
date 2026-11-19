from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    # Search results prefix field names with their entity ('track_name'); pages do not.
    renames: ClassVar[dict[str, str]] = {}

    @model_validator(mode="before")
    @classmethod
    def _page_names(cls, data: Any) -> Any:  # noqa: ANN401 -- raw input of any shape
        if not isinstance(data, dict):
            return data
        return {cls.renames.get(name, name): value for name, value in data.items()}


class Artist(_Model):
    """Credited artist; `type` tells artists from remixers."""

    renames = {"artist_id": "id", "artist_name": "name", "artist_type_name": "type"}

    id: int | None = None
    name: str
    type: str | None = None


class Named(_Model):
    """Genre, sub-genre, or label."""

    renames = {"genre_name": "name", "label_name": "name"}

    name: str | None = None


class Genre(Named):
    """Genre of a track page, with its sub-genre."""

    sub_genre: Named | None = None


class ReleaseRef(_Model):
    """Release a track appears on."""

    renames = {"release_id": "id", "release_name": "name"}

    id: int | None = None
    name: str | None = None
    slug: str | None = None
    catalog_number: str | None = None
    release_date: str | None = None


class Track(_Model):
    """Track of a track page or of search results."""

    renames = {"track_id": "id", "track_name": "name", "key_name": "key"}

    id: int
    name: str
    mix_name: str | None = None
    bpm: float | None = None
    key: str | None = None
    isrc: str | None = None
    artists: list[Artist] = []

    # A track page gives one genre object, search results a list.
    genre: Genre | list[Named] | None = None

    release: ReleaseRef | None = None
    label: Named | None = None
    catalog_number: str | None = None
    publish_date: str | None = None
    release_date: str | None = None


class Release(_Model):
    """Release of a release page or of search results."""

    renames = {"release_id": "id", "release_name": "name"}

    id: int
    name: str
    slug: str | None = None
    catalog_number: str | None = None
    upc: str | None = None
    label: Named | None = None
    artists: list[Artist] = []
    remixers: list[Artist] = []
    genre: list[Named] = []
    publish_date: str | None = None
    new_release_date: str | None = None
    release_date: str | None = None


class ChartOwner(_Model):
    """DJ profile that published a chart."""

    owner_name: str | None = None


class Chart(_Model):
    """DJ chart that lists a track."""

    id: int
    name: str
    slug: str | None = None
    publish_date: str | None = None
    artist: Artist | None = None
    person: ChartOwner | None = None


class Charts(_Model):
    """Page of charts that list a track."""

    results: list[Chart] = []


class TrackSearch(_Model):
    """Track search results."""

    data: list[Track] = []


class ReleaseSearch(_Model):
    """Release search results."""

    data: list[Release] = []
