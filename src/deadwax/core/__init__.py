"""Library internals shared by deadwax layers; the supported public API is `deadwax`."""

from .errors import ConfigurationError, DeadwaxError, InvalidQueryError

__all__ = ["ConfigurationError", "DeadwaxError", "InvalidQueryError"]
