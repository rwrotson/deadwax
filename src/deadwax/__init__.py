import logging

from .core import ConfigurationError, DeadwaxError, InvalidQueryError

# Records stay silent unless the application configures logging.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = ["ConfigurationError", "DeadwaxError", "InvalidQueryError"]
