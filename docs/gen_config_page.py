import html
import json
import re
from collections.abc import Iterator

import mkdocs_gen_files
from pydantic.fields import FieldInfo

from deadwax.cli.settings import Settings, env_fields, nested_model

PREFIX = "DEADWAX_"


def type_name(field: FieldInfo) -> str:
    """Format a field type for a Markdown table cell."""
    name = str(field.annotation).replace("typing.", "").replace("pathlib.", "")
    name = name.replace("_local.", "").replace("<class '", "").replace("'>", "")
    name = re.sub(r"\b(?:[a-z_]+\.)+([A-Za-z_]\w*)", r"\1", name)

    # A backslash-escaped pipe stays visible inside a code span, so use an HTML entity.
    return f"<code>{html.escape(name).replace('|', '&#124;')}</code>"


def default_value(field: FieldInfo) -> str:
    """Format a field default for a Markdown table cell."""
    if field.is_required():
        return "required"
    value = field.get_default(call_default_factory=True)
    return "—" if value is None else f"`{json.dumps(value, default=str)}`"


def table(rows: Iterator[tuple[str, FieldInfo]]) -> list[str]:
    """Build a configuration table from setting fields."""
    lines = ["| Variable | Type | Default | Description |", "| --- | --- | --- | --- |"]

    for variable, field in rows:
        description = field.description or ""
        lines.append(
            f"| `{variable}` | {type_name(field)} | {default_value(field)} | {description} |",
        )

    return lines


lines = [
    "# Configuration",
    "",
    f"This page is generated from `deadwax.cli.settings.Settings`. The `deadwax` command reads "
    "command-line flags, then "
    f"`{PREFIX}*` environment variables, then `.env` in the working directory, then a TOML "
    f"file (`--config`, `{PREFIX}CONFIG_FILE`, or `config.toml` in the user configuration "
    "directory); the first one that sets a value wins. The library itself does not read them. "
    f"Nested sections use `__`, for example `{PREFIX}LOG__LEVEL` or "
    f"`{PREFIX}SOURCES__DISCOGS__TOKEN`; in TOML they are tables such as `[log]` or "
    "`[sources.discogs]`. Empty values use the default.",
]

top_level = [
    (variable, field)
    for variable, field in env_fields()
    if "__" not in variable.removeprefix(PREFIX)
]
if top_level:
    lines += ["", "## Application", "", *table(iter(top_level))]

for name, field in Settings.model_fields.items():
    section = nested_model(field)
    if section is None:
        continue
    prefix = f"{PREFIX}{name.upper()}__"
    lines += ["", f"## {name.capitalize()}", "", (section.__doc__ or "").strip()]
    sources = [
        (source, model)
        for source, source_field in section.model_fields.items()
        if (model := nested_model(source_field)) is not None
    ]
    if not sources:
        lines += ["", *table(env_fields(section, prefix))]
    for source, model in sources:
        lines += ["", f"### {source}", "", (model.__doc__ or "").strip(), ""]
        lines += table(env_fields(model, f"{prefix}{source.upper()}__"))

with mkdocs_gen_files.open("configuration.md", "w") as fd:
    fd.write("\n".join(lines) + "\n")

mkdocs_gen_files.set_edit_path("configuration.md", "../src/deadwax/cli/settings.py")
