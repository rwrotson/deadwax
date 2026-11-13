from pydantic import BaseModel, ConfigDict, TypeAdapter


class ApiModel(BaseModel):
    """Base for ListenBrainz and CritiqueBrainz responses; unknown fields are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class Popularity(ApiModel):
    """Listens and listeners of a recording or release group across ListenBrainz."""

    total_listen_count: int | None = None
    total_user_count: int | None = None


class SimilarRecording(ApiModel):
    """Recording listened to in the same sessions, with a relative score."""

    recording_mbid: str
    recording_name: str
    artist_credit_name: str | None = None
    score: float | None = None


class SimilarArtist(ApiModel):
    """Artist listened to in the same sessions, with a relative score."""

    artist_mbid: str
    name: str
    score: float | None = None


class User(ApiModel):
    """Author of a CritiqueBrainz review."""

    display_name: str | None = None


class Review(ApiModel):
    """CritiqueBrainz review; `source` names the publication of a republished review."""

    id: str
    text: str | None = None
    rating: int | None = None
    language: str | None = None
    published_on: str | None = None
    source: str | None = None
    user: User | None = None


class ReviewList(ApiModel):
    """CritiqueBrainz reviews of one entity."""

    reviews: list[Review] = []


popularity_list = TypeAdapter(list[Popularity])
similar_recordings = TypeAdapter(list[SimilarRecording])
similar_artists = TypeAdapter(list[SimilarArtist])
