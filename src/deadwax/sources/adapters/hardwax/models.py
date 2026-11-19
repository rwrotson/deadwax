from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class FeedItem(_Model):
    """One release of the search feed; its title is 'Artist: Title'."""

    title: str
    url: str
    content_html: str = ""


class Feed(_Model):
    """Search results as a JSON Feed."""

    items: list[FeedItem] = []
