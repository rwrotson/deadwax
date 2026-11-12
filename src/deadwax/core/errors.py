class DeadwaxError(Exception):
    """Base class for errors raised by the library."""


class InvalidQueryError(DeadwaxError, ValueError):
    """The query cannot be parsed or is inconsistent."""


class ConfigurationError(DeadwaxError):
    """A setting, credential or optional dependency required for an operation is missing."""


class SourceError(DeadwaxError):
    """A source could not answer a request."""

    def __init__(self, message: str, *, url: str | None = None) -> None:
        super().__init__(message)
        self.url = url


class BlockedError(SourceError):
    """A source answered with an anti-bot challenge or refused access."""


class RateLimitedError(SourceError):
    """A source asked to wait longer than the client is allowed to."""


class NotFoundError(SourceError):
    """A source has no page for the requested record."""
