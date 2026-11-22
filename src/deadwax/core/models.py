from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Discriminator, Field, field_validator
from pydantic import Tag as Variant

from deadwax.core.query import EntityKind, IdKind, Query, kind_tag


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Scope(StrEnum):
    """What a fact describes: the recording itself, its release, or something wider."""

    RECORDING = "recording"
    WORK = "work"
    RELEASE = "release"
    RELEASE_GROUP = "release_group"
    ARTIST = "artist"
    LABEL = "label"


class VersionKind(StrEnum):
    """Version of a recording or release; `original` means no version marker was found."""

    ORIGINAL = "original"
    REMIX = "remix"
    LIVE = "live"
    DEMO = "demo"
    COVER = "cover"
    INSTRUMENTAL = "instrumental"
    ACOUSTIC = "acoustic"
    EDIT = "edit"

    # Longer DJ-oriented mix such as 'Extended Mix' or 'Club Mix'.
    EXTENDED = "extended"

    # The artist's own dub version; a dub by someone else is a remix.
    DUB = "dub"

    ALTERNATE = "alternate"
    REISSUE = "reissue"
    REMASTER = "remaster"


class TagKind(StrEnum):
    """Vocabulary a tag comes from."""

    GENRE = "genre"
    SECONDARY_GENRE = "secondary_genre"
    STYLE = "style"
    MOOD = "mood"
    THEME = "theme"
    DESCRIPTOR = "descriptor"
    TAG = "tag"


class TextKind(StrEnum):
    """Origin of a text about the record."""

    REVIEW = "review"
    EDITORIAL = "editorial"
    LABEL = "label"
    SHOP = "shop"
    WIKI = "wiki"
    USER = "user"
    LYRICS = "lyrics"

    # Host's note on a radio play or show.
    BROADCAST = "broadcast"


class RelationKind(StrEnum):
    """How a related entity is connected to the record."""

    MEMBER = "member"
    PROJECT = "project"

    # Another relation to an artist; the note names its source type, such as 'founder'.
    ASSOCIATED = "associated"

    # Another name of the artist or label, such as an alias or a name variation.
    ALIAS = "alias"

    LABEL = "label"
    PARENT_LABEL = "parent_label"

    # Imprint or label owned by the queried label.
    SUBLABEL = "sublabel"

    LABEL_RELEASE = "label_release"

    # A main release of the queried artist.
    RELEASE = "release"

    APPEARS_ON = "appears_on"
    COMPILATION = "compilation"
    MIX = "mix"
    BROADCAST = "broadcast"
    COVER_OF = "cover_of"
    COVERED_BY = "covered_by"
    REMIX_OF = "remix_of"
    REMIXED_BY = "remixed_by"
    SAMPLES = "samples"
    SAMPLED_BY = "sampled_by"
    INTERPOLATES = "interpolates"
    INTERPOLATED_BY = "interpolated_by"
    REPOSTED_BY = "reposted_by"

    # A DJ's chart that lists the record; the target's artist is the DJ.
    CHARTED_BY = "charted_by"
    CHARTED_IN = "charted_in"

    SIMILAR = "similar"

    # A recording by an artist similar to the record's artist (ListenBrainz LB Radio).
    SIMILAR_ARTIST_RECORDING = "similar_artist_recording"

    CO_PLAYED = "co_played"
    OTHER_VERSION = "other_version"


class MetricKind(StrEnum):
    """What a count measures."""

    LISTENS = "listens"
    LISTENERS = "listeners"
    LIKES = "likes"
    REPOSTS = "reposts"

    # Score a service computes from its own plays, such as Spotify's 0-100 popularity.
    POPULARITY = "popularity"
    USER_SCORE = "user_score"
    RATING_VOTES = "rating_votes"


class EntityType(StrEnum):
    """Type of a related entity."""

    RECORDING = "recording"
    RELEASE = "release"
    ARTIST = "artist"
    LABEL = "label"
    WORK = "work"
    MIX = "mix"
    BROADCAST = "broadcast"
    CHART = "chart"


class LinkTarget(StrEnum):
    """What a link opens."""

    TRACK = "track"
    ALBUM = "album"
    ARTIST = "artist"
    LABEL = "label"
    OTHER = "other"


class ArtistType(StrEnum):
    """What kind of performer an artist is."""

    PERSON = "person"
    GROUP = "group"
    ORCHESTRA = "orchestra"
    CHOIR = "choir"
    CHARACTER = "character"
    OTHER = "other"


class ErrorKind(StrEnum):
    """Why an adapter contributed nothing or only part of its data."""

    SKIPPED = "skipped"

    # No selected source looks up records of the query's kind.
    UNSUPPORTED = "unsupported"

    FAILED = "failed"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    NO_MATCH = "no_match"


class Provenance(_Model):
    """Adapter and page where a fact was found."""

    source: str
    url: str | None = None


class Sourced[T](_Model):
    """A value with the places it was found."""

    value: T
    sources: list[Provenance]


class Attributed(_Model):
    """Base for facts that list where they were found."""

    sources: list[Provenance]


class Fact(Attributed):
    """Base for facts about part of the record or its context."""

    scope: Scope


class VersionInfo(_Model):
    """Version of a record with the title marker it was derived from."""

    kind: VersionKind = VersionKind.ORIGINAL
    detail: str | None = Field(default=None, description="Marker text, such as 'Four Tet Remix'")


class LabelRef(Attributed):
    """Label and catalog number of a release."""

    name: str
    catalog_number: str | None = None


class ExternalId(Attributed):
    """Identifier of the record in an external namespace."""

    kind: IdKind
    value: str


class Discrepancy(_Model):
    """Values of one field on which sources disagree."""

    field: str
    values: list[Sourced[str]]


def _record_kind(kind: EntityKind | None) -> EntityKind | None:
    if kind not in {EntityKind.TRACK, EntityKind.ALBUM, None}:
        raise ValueError(f"a {kind} is not a track or album")
    return kind


class IdentityBase(_Model):
    """Parts of an identity shared by every record kind."""

    kind: EntityKind | None = None
    external_ids: list[ExternalId] = []
    discrepancies: list[Discrepancy] = []


class RecordIdentity(IdentityBase):
    """Canonical identity of a track or album and disagreements between sources."""

    kind: EntityKind | None = Field(default=None, description="Track, album, or unknown")
    artist: Sourced[str] | None = None
    title: Sourced[str] | None = None
    version: VersionInfo = VersionInfo()
    date: Sourced[str] | None = Field(default=None, description="ISO date, possibly partial")
    bpm: Sourced[float] | None = Field(default=None, description="Tempo in beats per minute")
    key: Sourced[str] | None = Field(default=None, description="Musical key as a source gives it")
    labels: list[LabelRef] = []
    isrcs: list[Sourced[str]] = []
    upcs: list[Sourced[str]] = []
    copyrights: list[Sourced[str]] = Field(
        default=[],
        description="Copyright (©) and phonographic copyright (℗) lines",
    )

    @field_validator("kind")
    @classmethod
    def _record_kind(cls, kind: EntityKind | None) -> EntityKind | None:
        return _record_kind(kind)

    @property
    def found(self) -> bool:
        """Whether any source identified the record."""
        return self.title is not None


class _NameIdentity(IdentityBase):
    name: Sourced[str] | None = None
    disambiguation: Sourced[str] | None = Field(
        default=None,
        description="Comment that tells namesakes apart",
    )
    country: Sourced[str] | None = Field(default=None, description="Country as a source gives it")
    location: Sourced[str] | None = Field(default=None, description="Location as a source gives it")
    begin: Sourced[str] | None = Field(default=None, description="ISO date, possibly partial")
    end: Sourced[str] | None = Field(default=None, description="ISO date, possibly partial")

    @property
    def found(self) -> bool:
        """Whether any source identified the record."""
        return self.name is not None


class ArtistIdentity(_NameIdentity):
    """Canonical identity of an artist and disagreements between sources."""

    kind: Literal[EntityKind.ARTIST] = EntityKind.ARTIST
    type: Sourced[ArtistType] | None = None


class LabelIdentity(_NameIdentity):
    """Canonical identity of a label and disagreements between sources."""

    kind: Literal[EntityKind.LABEL] = EntityKind.LABEL


# Tag of the identity or candidate variant of a track, an album, or a record of unknown kind.
_RECORD = "record"


def _record_tag(value: object) -> str:
    tag = kind_tag(value)
    return tag if tag in {EntityKind.ARTIST, EntityKind.LABEL} else _RECORD


type Identity = Annotated[
    Annotated[RecordIdentity, Variant(_RECORD)]
    | Annotated[ArtistIdentity, Variant(EntityKind.ARTIST)]
    | Annotated[LabelIdentity, Variant(EntityKind.LABEL)],
    Discriminator(_record_tag),
]


class Tag(Fact):
    """Genre, style, mood, or free-form tag."""

    name: str
    kind: TagKind = TagKind.TAG
    context_url: str | None = Field(
        default=None,
        description="Episode or set whose context this tag describes, rather than the record",
    )
    weight: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Relative weight in the source, scaled to 0-1",
    )


class Credit(Fact):
    """Person or group with their role on the record."""

    role: str
    name: str
    detail: str | None = Field(default=None, description="Instruments or tracks the credit covers")


class Rating(_Model):
    """Score given by a review."""

    value: float | None = None
    scale: float | None = None
    text: str | None = Field(default=None, description="Score as printed, such as 'B+'")


class Text(Fact):
    """Review, description, or note about the record."""

    kind: TextKind
    body: str
    title: str | None = None
    author: str | None = None
    publication: str | None = None
    date: str | None = None
    rating: Rating | None = None
    language: str | None = None


class Metric(Fact):
    """Count or score that one source reports; never combined across sources."""

    kind: MetricKind
    value: float
    scale: float | None = Field(default=None, description="Highest possible value, if bounded")


class Entity(_Model):
    """Something the record is related to."""

    type: EntityType
    name: str
    artist: str | None = None
    date: str | None = None
    url: str | None = None
    ids: dict[IdKind, str] = {}


class Relation(Fact):
    """Connection between the record and another entity."""

    kind: RelationKind
    target: Entity
    note: str | None = None
    recording_offset: int | None = Field(
        default=None,
        ge=0,
        description="Seconds into the queried recording",
    )
    target_offset: int | None = Field(
        default=None,
        ge=0,
        description="Seconds into the related recording",
    )
    element: str | None = Field(
        default=None,
        description="Sound element identified in a sample connection",
    )


class Link(Attributed):
    """Page of the record or its artist on a service."""

    service: str
    url: str
    target: LinkTarget
    preview_url: str | None = None


class ReviewLink(Attributed):
    """Page containing a review of the record."""

    publication: str | None = None
    url: str


class SourceAccess(_Model):
    """Configured routes used to obtain a source's answers."""

    api: bool = False
    html_transports: list[str] = Field(default_factory=list)
    browser_headless: bool | None = None

    # Whether a challenged headless browser retries with a window.
    headed_fallback: bool = False


class AdapterError(_Model):
    """Adapter that did not answer, or answered only in part, and why."""

    source: str
    kind: ErrorKind
    reason: str
    url: str | None = None
    access: SourceAccess | None = None


class CandidateLabel(_Model):
    """Label and catalog number as given by one source."""

    name: str
    catalog_number: str | None = None


class RecordCandidate(_Model):
    """One adapter's view of the track or album it found."""

    kind: EntityKind | None = Field(default=None, description="Track, album, or unknown")
    artist: str
    title: str
    version: VersionInfo | None = Field(
        default=None,
        description="Explicit version; derived from the title when unset",
    )
    date: str | None = None
    bpm: float | None = Field(default=None, gt=0, description="Tempo in beats per minute")
    key: str | None = Field(default=None, description="Musical key, such as 'A Minor' or '8A'")
    labels: list[CandidateLabel] = []
    isrcs: list[str] = []
    upcs: list[str] = []
    copyrights: list[str] = []
    ids: dict[IdKind, str] = {}
    url: str | None = None

    @field_validator("kind")
    @classmethod
    def _record_kind(cls, kind: EntityKind | None) -> EntityKind | None:
        return _record_kind(kind)


class _NameCandidate(_Model):
    name: str
    disambiguation: str | None = None
    country: str | None = None
    location: str | None = None
    begin: str | None = Field(default=None, description="ISO date, possibly partial")
    end: str | None = Field(default=None, description="ISO date, possibly partial")
    ids: dict[IdKind, str] = {}
    url: str | None = None


class ArtistCandidate(_NameCandidate):
    """One adapter's view of the artist it found."""

    kind: Literal[EntityKind.ARTIST] = EntityKind.ARTIST
    type: ArtistType | None = None


class LabelCandidate(_NameCandidate):
    """One adapter's view of the label it found."""

    kind: Literal[EntityKind.LABEL] = EntityKind.LABEL


type NameCandidate = ArtistCandidate | LabelCandidate

type Candidate = Annotated[
    Annotated[RecordCandidate, Variant(_RECORD)]
    | Annotated[ArtistCandidate, Variant(EntityKind.ARTIST)]
    | Annotated[LabelCandidate, Variant(EntityKind.LABEL)],
    Discriminator(_record_tag),
]


class Facts(_Model):
    """Facts gathered about a record, each with its sources."""

    tags: list[Tag] = []
    credits: list[Credit] = []
    texts: list[Text] = []
    relations: list[Relation] = []
    metrics: list[Metric] = []
    links: list[Link] = []
    review_links: list[ReviewLink] = []


class Partial(Facts):
    """Everything one adapter found; facts are kept only if the candidate matches the query."""

    source: str
    candidate: Candidate | None = None
    errors: list[AdapterError] = []


class Dossier(Facts):
    """Everything known about one record, with the source of every fact."""

    query: Query
    identity: Identity
    errors: list[AdapterError] = []
    generated_at: AwareDatetime

    @property
    def found(self) -> bool:
        """Whether any source identified the record."""
        return self.identity.found
