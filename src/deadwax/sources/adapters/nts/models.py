from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator


def _stripped(value: object) -> object:
    return (value.strip() or None) if isinstance(value, str) else value


# Non-blank text, stripped; blank text reads as absent.
type Text = Annotated[str | None, BeforeValidator(_stripped)]


class ApiModel(BaseModel):
    """Base for NTS API responses; unknown fields are ignored and null reads as absent."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data: object) -> object:
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value is not None}
        return data


class Artist(ApiModel):
    """Artist of a search hit."""

    name: Text = None


class Article(ApiModel):
    """Episode a search hit was played in."""

    url: Text = None
    path: Text = None
    name: Text = None


class Hit(ApiModel):
    """Track of the public track index."""

    title: Text = None
    artists: list[Artist] = []
    article: Article = Article()


class Search(ApiModel):
    """Results of a track search."""

    results: list[Hit] = []


class Track(ApiModel):
    """Track of an episode tracklist."""

    artist: Text = None
    title: Text = None


class Tracklist(ApiModel):
    """Tracklist of an episode."""

    results: list[Track] = []


class Embeds(ApiModel):
    """Data embedded in an episode."""

    tracklist: Tracklist = Tracklist()


class Genre(ApiModel):
    """Genre of an episode."""

    value: Text = None
    name: Text = None


class Episode(ApiModel):
    """NTS episode with its genres and tracklist."""

    name: Text = None
    broadcast: Text = None
    broadcast_date: Text = None
    date: Text = None
    genres: list[Genre] = []
    embeds: Embeds = Embeds()
