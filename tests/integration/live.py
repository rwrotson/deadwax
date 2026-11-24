from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from deadwax import AdapterError, ErrorKind


@dataclass
class LiveRun:
    lines: list[str] = field(default_factory=list)
    pending: list[pytest.Item] = field(default_factory=list)
    retrying: bool = False


class MusicBrainzUnavailableError(AssertionError):
    def __init__(self) -> None:
        super().__init__("MusicBrainz returned HTTP 503 after HTTP retries")


def failed_sources(errors: Sequence[AdapterError]) -> list[AdapterError]:
    return [error for error in errors if error.kind is ErrorKind.FAILED]


def only_musicbrainz_503(failures: Sequence[AdapterError]) -> bool:
    return bool(failures) and all(
        error.source == "musicbrainz" and error.reason == "HTTP 503" for error in failures
    )
