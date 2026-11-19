from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class Track(_Model):
    """One entry of a product's playlist."""

    trackname: str | None = None


class Product(_Model):
    """One product of the search API; `slug` is its page path, such as 'product/<name>/<id>'."""

    artist: str
    album: str
    slug: str
    product_playlist: list[Track] = []
