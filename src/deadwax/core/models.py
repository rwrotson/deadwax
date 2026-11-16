from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from deadwax.core.query import EntityKind, IdKind, Query


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
    LABEL = "label"
    LABEL_RELEASE = "label_release"
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


class ErrorKind(StrEnum):
    """Why an adapter contributed nothing or only part of its data."""

    SKIPPED = "skipped"
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


class Identity(_Model):
    """Canonical identity of the record and disagreements between sources."""

    kind: EntityKind | None = None
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
    external_ids: list[ExternalId] = []
    discrepancies: list[Discrepancy] = []


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


class AdapterError(_Model):
    """Adapter that did not answer, or answered only in part, and why."""

    source: str
    kind: ErrorKind
    reason: str
    url: str | None = None


class CandidateLabel(_Model):
    """Label and catalog number as given by one source."""

    name: str
    catalog_number: str | None = None


class RecordCandidate(_Model):
    """One adapter's view of the record it found."""

    kind: EntityKind | None = None
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


class Partial(_Model):
    """Everything one adapter found; facts are kept only if the candidate matches the query."""

    source: str
    candidate: RecordCandidate | None = None
    tags: list[Tag] = []
    credits: list[Credit] = []
    texts: list[Text] = []
    relations: list[Relation] = []
    metrics: list[Metric] = []
    links: list[Link] = []
    review_links: list[ReviewLink] = []
    errors: list[AdapterError] = []


class Dossier(_Model):
    """Everything known about one record, with the source of every fact."""

    query: Query
    identity: Identity
    tags: list[Tag] = []
    credits: list[Credit] = []
    texts: list[Text] = []
    relations: list[Relation] = []
    metrics: list[Metric] = []
    links: list[Link] = []
    review_links: list[ReviewLink] = []
    errors: list[AdapterError] = []
    generated_at: AwareDatetime

    @property
    def found(self) -> bool:
        """Whether any source identified the record."""
        return self.identity.title is not None
