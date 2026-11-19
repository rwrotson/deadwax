from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Base for SecondHandSongs API responses; unknown fields are ignored."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        alias_generator=to_camel,
        populate_by_name=True,
    )


class Performer(ApiModel):
    """Artist credited with a performance or release."""

    uri: str | None = None
    name: str


class PerformanceRef(ApiModel):
    """Performance as other entities list it."""

    uri: str
    title: str
    performer: Performer | None = None
    is_original: bool | None = None


class SearchResults(ApiModel):
    """One page of performance search results."""

    result_page: list[PerformanceRef] = []


class WorkRef(ApiModel):
    """Work as other entities list it; `original` is set where a performance covers it."""

    uri: str
    title: str
    original: PerformanceRef | None = None


class Performance(ApiModel):
    """A recorded performance of one or more works."""

    uri: str
    title: str
    performer: Performer | None = None
    is_original: bool | None = None
    date: str | None = None
    first_release_date: str | None = None
    works: list[WorkRef] = []
    originals: list[WorkRef] = []
    covers: list[PerformanceRef] = []


class Writer(ApiModel):
    """Person or group credited with writing a work."""

    uri: str | None = None
    common_name: str


class Work(ApiModel):
    """A song with its writers and the works it adapts or that adapt it."""

    uri: str
    title: str
    credits: list[Writer] = []
    based_on: list[WorkRef] = []
    derived_works: list[WorkRef] = []
