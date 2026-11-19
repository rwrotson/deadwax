from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _non_blank(value: object) -> object:
    return value if not isinstance(value, str) or value.strip() else None


# Text as sent when it is not blank; blank text reads as absent.
type Text = Annotated[str | None, BeforeValidator(_non_blank)]


class ApiModel(BaseModel):
    """Base for RA GraphQL responses; unknown fields are ignored and null reads as absent."""

    model_config = ConfigDict(frozen=True, extra="ignore", validate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data: object) -> object:
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value is not None}
        return data


class Author(ApiModel):
    """Author of a review."""

    name: Text = None


class Biography(ApiModel):
    """Artist biography; the blurb is HTML."""

    blurb: Text = None


class Artist(ApiModel):
    """Artist of a reviewed record."""

    name: Text = None
    biography: Biography = Biography()


class Label(ApiModel):
    """Label of a reviewed record; the blurb is HTML."""

    name: Text = None
    blurb: Text = None


class Review(ApiModel):
    """RA review; the content is HTML."""

    title: Text = None
    type: Text = None
    content: Text = None
    date: Text = None
    author: Author = Author()
    labels: list[Label] = []
    artists: list[Artist] = []


class SearchHit(ApiModel):
    """Review found by the site search."""

    value: Text = None
    content_url: Text = Field(default=None, alias="contentUrl")


class Data(ApiModel):
    """Data of a search or review query."""

    search: list[SearchHit] = []
    review: Review = Review()


class Response(ApiModel):
    """GraphQL response."""

    data: Data = Data()
    errors: list[object] = []
