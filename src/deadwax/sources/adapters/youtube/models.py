from pydantic import BaseModel, ConfigDict


class _Api(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class ResourceId(_Api):
    """ID of a search result; videos and playlists fill different fields."""

    videoId: str | None = None  # noqa: N815 -- the API's field name
    playlistId: str | None = None  # noqa: N815 -- the API's field name


class Snippet(_Api):
    """Title and channel of a search result, HTML-escaped."""

    title: str = ""
    channelTitle: str = ""  # noqa: N815 -- the API's field name


class SearchItem(_Api):
    """One search result."""

    id: ResourceId
    snippet: Snippet


class SearchResponse(_Api):
    """Answer of the search endpoint."""

    items: list[SearchItem] = []
