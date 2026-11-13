from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LogSettings(BaseModel):
    """Console and optional rotating file logging."""

    level: LogLevel = Field(default="INFO", description="Root log level")
    console_level: LogLevel = Field(default="DEBUG", description="Minimum level printed to stderr")
    file_level: LogLevel = Field(default="INFO", description="Minimum level written to the file")
    format: Literal["console", "json"] = Field(
        default="console",
        description="Console log renderer; file logs are always JSON",
    )
    dir: Path | None = Field(
        default=None,
        description="Log directory; file logging is disabled if unset",
    )
    file_name: str = Field(
        default="deadwax.log",
        description="Log file basename without directory separators",
    )
    file_max_bytes: int = Field(
        default=4 * 1024 * 1024,
        ge=0,
        description="File size that triggers rotation",
    )
    file_backup_count: int = Field(default=5, ge=0, description="Rotated files to keep")

    @field_validator("file_name")
    @classmethod
    def _require_basename(cls, value: str) -> str:
        """Keep the log file inside the configured directory."""
        if value in {"", ".", ".."} or "/" in value or "\\" in value:
            raise ValueError("Log file name must be a basename")
        return value


class RunLogSettings(BaseModel):
    """Journal of lookups: one JSON Lines file of trace events per run and an index of runs."""

    enabled: bool = Field(default=True, description="Write a journal entry for every run")
    dir: Path | None = Field(
        default=None,
        description="Journal directory; required when the journal is enabled",
    )
    retention_days: int = Field(
        default=90,
        ge=0,
        description="Days runs are kept; 0 keeps them forever",
    )
    dossier: bool = Field(
        default=True,
        description="Store the final dossier in the run's last event",
    )
