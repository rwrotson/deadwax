from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator


def _non_blank(value: object) -> object:
    return value if not isinstance(value, str) or value.strip() else None


# Text as sent when it is not blank; blank text reads as absent.
type Text = Annotated[str | None, BeforeValidator(_non_blank)]


class ApiModel(BaseModel):
    """Base for Genius API responses; unknown fields are ignored and null reads as absent."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data: object) -> object:
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value is not None}
        return data


class Envelope(ApiModel):
    """Every API answer wraps its data in `response`."""

    response: dict[str, object] = {}


class RichText(ApiModel):
    """Rich-text field requested with its plain rendering."""

    plain: str | None = None


class Artist(ApiModel):
    """Artist credited on a song."""

    name: Text = None


class Song(ApiModel):
    """Genius song as search, song, and relationship data list it."""

    id: int | None = None
    title: str | None = None
    url: Text = None
    primary_artist: Artist = Artist()
    description: RichText = RichText()
    writer_artists: list[Artist] = []
    producer_artists: list[Artist] = []
    song_relationships: list[Relationship] = []


class Relationship(ApiModel):
    """Songs related to a song in one way, such as samples or covers."""

    relationship_type: str | None = None
    songs: list[Song] = []


class Hit(ApiModel):
    """Search hit."""

    result: Song = Song()


class Search(ApiModel):
    """Results of a song search."""

    hits: list[Hit] = []


class SongData(ApiModel):
    """Answer of the song endpoint."""

    song: Song = Song()


class Annotation(ApiModel):
    """User annotation of a lyric fragment."""

    url: Text = None
    body: RichText = RichText()


class Referent(ApiModel):
    """Lyric fragment with its annotations."""

    annotations: list[Annotation] = []


class Referents(ApiModel):
    """One page of a song's annotated fragments."""

    referents: list[Referent] = []
    next_page: int | None = None
