from pydantic import BaseModel, ConfigDict, Field


class _Page(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class Entity(_Page):
    """Song or album the page is about, as the seed platform knows it."""

    type: str
    id: str | None = None
    provider: str | None = None
    title: str | None = None
    artist_name: str | None = Field(default=None, alias="artistName")
    isrc: str | None = None
    upc: str | None = None


class PlatformLink(_Page):
    """Link of one platform; platforms Odesli did not match have no URL."""

    platform: str
    url: str | None = None
    show: bool = True


class Section(_Page):
    """Block of the page, such as the 'listen' and 'buy' link lists."""

    section_id: str = Field(default="", alias="sectionId")
    links: list[PlatformLink] = []


class PageData(_Page):
    """Data the song.link page renders."""

    entity_unique_id: str = Field(alias="entityUniqueId")
    page_url: str | None = Field(default=None, alias="pageUrl")
    entity: Entity | None = Field(default=None, alias="entityData")
    sections: list[Section] = []


class _PageProps(_Page):
    page_data: PageData | None = Field(default=None, alias="pageData")


class _Props(_Page):
    page_props: _PageProps = Field(default=_PageProps(), alias="pageProps")


class NextData(_Page):
    """Next.js data embedded in a song.link page."""

    props: _Props = _Props()
