class DeadwaxError(Exception):
    """Base class for errors raised by the library."""


class InvalidQueryError(DeadwaxError, ValueError):
    """The query cannot be parsed or is inconsistent."""


class ConfigurationError(DeadwaxError):
    """A setting, credential or optional dependency required for an operation is missing."""
