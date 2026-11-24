from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base for MusicBrainz responses; unknown fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class ArtistRef(ApiModel):
    """Artist as referenced from credits and relations."""

    id: str
    name: str


class ArtistCredit(ApiModel):
    """One name of an artist credit with the phrase joining it to the next."""

    name: str
    joinphrase: str = ""
    artist: ArtistRef


class ReleaseGroupRef(ApiModel):
    """Release group as embedded in releases and search results."""

    id: str
    title: str = ""
    primary_type: str | None = Field(default=None, alias="primary-type")
    secondary_types: list[str] = Field(default=[], alias="secondary-types")
    first_release_date: str | None = Field(default=None, alias="first-release-date")


class ReleaseRef(ApiModel):
    """Release as embedded in recordings and release groups."""

    id: str
    title: str = ""
    status: str | None = None
    date: str | None = None
    release_group: ReleaseGroupRef | None = Field(default=None, alias="release-group")


class Tag(ApiModel):
    """Folksonomy tag or genre with its vote count."""

    name: str
    count: int = 0


class UrlRef(ApiModel):
    """External URL of a relation."""

    resource: str


class WorkRef(ApiModel):
    """Work as referenced from relations."""

    id: str
    title: str


class RecordingRef(ApiModel):
    """Recording as referenced from relations."""

    id: str
    title: str
    disambiguation: str = ""
    video: bool | None = None
    artist_credit: list[ArtistCredit] = Field(default=[], alias="artist-credit")


class LabelRef(ApiModel):
    """Label of a release."""

    id: str
    name: str


class LifeSpan(ApiModel):
    """Dates an artist or label was active, possibly partial."""

    begin: str | None = None
    end: str | None = None


class Alias(ApiModel):
    """Other name of an artist or label."""

    name: str
    type: str | None = None


class Relation(ApiModel):
    """Typed relationship to another entity or a URL."""

    type: str
    direction: str = "forward"
    target_type: str = Field(alias="target-type")
    attributes: list[str] = []
    artist: ArtistRef | None = None
    label: LabelRef | None = None
    url: UrlRef | None = None
    work: WorkRef | None = None
    recording: RecordingRef | None = None
    release: ReleaseRef | None = None
    release_group: ReleaseGroupRef | None = Field(default=None, alias="release_group")


class Recording(ApiModel):
    """Recording from a lookup or a search."""

    id: str
    title: str
    disambiguation: str = ""
    video: bool | None = None
    first_release_date: str | None = Field(default=None, alias="first-release-date")
    artist_credit: list[ArtistCredit] = Field(default=[], alias="artist-credit")
    isrcs: list[str] = []
    releases: list[ReleaseRef] = []
    tags: list[Tag] = []
    genres: list[Tag] = []
    relations: list[Relation] = []


class RecordingSearch(ApiModel):
    """Result of a recording search."""

    recordings: list[Recording] = []


class LabelInfo(ApiModel):
    """Label and catalog number of a release."""

    catalog_number: str | None = Field(default=None, alias="catalog-number")
    label: LabelRef | None = None


class Track(ApiModel):
    """Track of a medium with its recording."""

    title: str
    recording: Recording
    id: str | None = None
    number: str | None = None
    artist_credit: list[ArtistCredit] = Field(default=[], alias="artist-credit")


class Medium(ApiModel):
    """Disc or side of a release."""

    position: int | None = None
    track_count: int | None = Field(default=None, alias="track-count")
    pregap: Track | None = None
    tracks: list[Track] = []


class Release(ApiModel):
    """Release from a lookup."""

    id: str
    title: str
    status: str | None = None
    date: str | None = None
    barcode: str | None = None
    disambiguation: str = ""
    artist_credit: list[ArtistCredit] = Field(default=[], alias="artist-credit")
    label_info: list[LabelInfo] = Field(default=[], alias="label-info")
    release_group: ReleaseGroupRef | None = Field(default=None, alias="release-group")
    media: list[Medium] = []
    relations: list[Relation] = []


class ReleaseGroup(ApiModel):
    """Release group from a lookup or a search."""

    id: str
    title: str
    disambiguation: str = ""
    primary_type: str | None = Field(default=None, alias="primary-type")
    secondary_types: list[str] = Field(default=[], alias="secondary-types")
    first_release_date: str | None = Field(default=None, alias="first-release-date")
    artist_credit: list[ArtistCredit] = Field(default=[], alias="artist-credit")
    releases: list[ReleaseRef] = []
    tags: list[Tag] = []
    genres: list[Tag] = []
    relations: list[Relation] = []


class ReleaseGroupSearch(ApiModel):
    """Result of a release group search."""

    release_groups: list[ReleaseGroup] = Field(default=[], alias="release-groups")


class Work(ApiModel):
    """Work with its recordings and URLs."""

    id: str
    title: str
    relations: list[Relation] = []


class Artist(ApiModel):
    """Artist from a lookup or a search, with its relations."""

    id: str
    name: str
    type: str | None = None
    disambiguation: str = ""
    country: str | None = None
    life_span: LifeSpan = Field(default=LifeSpan(), alias="life-span")
    aliases: list[Alias] = []
    tags: list[Tag] = []
    genres: list[Tag] = []
    relations: list[Relation] = []


class ArtistSearch(ApiModel):
    """Result of an artist search."""

    artists: list[Artist] = []


class Label(ApiModel):
    """Label from a lookup or a search, with its relations."""

    id: str
    name: str
    disambiguation: str = ""
    country: str | None = None
    life_span: LifeSpan = Field(default=LifeSpan(), alias="life-span")
    aliases: list[Alias] = []
    tags: list[Tag] = []
    genres: list[Tag] = []
    relations: list[Relation] = []


class LabelSearch(ApiModel):
    """Result of a label search."""

    labels: list[Label] = []


class ReleaseGroupBrowse(ApiModel):
    """Page of an artist's release groups."""

    release_groups: list[ReleaseGroup] = Field(default=[], alias="release-groups")


class UrlEntity(ApiModel):
    """URL known to MusicBrainz with the entities it belongs to."""

    id: str
    resource: str
    relations: list[Relation] = []
