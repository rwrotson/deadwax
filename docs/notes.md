# Notes

## Build Backend

`uv_build` loads the `deadwax` package from `src/`:

```toml
[tool.uv.build-backend]
module-name = "deadwax"
module-root = "src"
```

The wheel includes `py.typed`, so type checkers use the package's inline annotations.

## structlog Integration

`deadwax.logs.setup_logging()` (the `logs` extra) connects [structlog](https://www.structlog.org/) to stdlib logging through `ProcessorFormatter`:

- Library modules use stdlib loggers; their records and structlog events share the same handlers.
- Console logs use colourised `ConsoleRenderer` output or JSON with `LogSettings(format="json")` (`DEADWAX_LOG__FORMAT=json` for the command).
- File logs use JSON and are written only when `LogSettings.dir` (`DEADWAX_LOG__DIR`) is set.
- Timestamps are ISO 8601 in UTC.
- `structlog.contextvars.bind_contextvars()` adds fields to subsequent logs in the current context.

The library never calls `setup_logging()` itself. An application that already configures logging or structlog should skip it.

## Documentation Toolchain

The site is built with [ProperDocs](https://properdocs.org/), a maintained continuation of MkDocs 1.x that reads the same configuration (`properdocs.yml`) and runs MkDocs themes and plugins unchanged. MkDocs 2.0 drops the plugin and theme system, and Material for MkDocs requires `mkdocs<2`, so the `mkdocs` package stays on 1.x as a library dependency of the plugins. Running `properdocs` instead of `mkdocs` also avoids the MkDocs 2.0 warnings printed by Material and the plugins.

[Zensical](https://zensical.org/), the successor to Material for MkDocs, does not support `mkdocs-gen-files` yet; the API reference and configuration pages depend on it.

## Commitizen & Versioning

[Commitizen](https://commitizen-tools.github.io/commitizen/) reads Conventional Commit messages to select the next version and update `CHANGELOG.md`. Its settings are in `pyproject.toml`:

```toml
version_provider = "uv"
update_changelog_on_bump = true
major_version_zero = true
```

The `commit-msg` hook checks Conventional Commit format.

## Publishing

The release workflow publishes version tags to PyPI with [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) only when the repository variable `PUBLISH_TO_PYPI` is `true` (Settings → Secrets and variables → Actions → Variables). Without it, a release builds the package and deploys documentation; install a tagged version from GitHub instead. To publish, on PyPI add a trusted publisher with the repository owner and name, workflow `release.yml`, and environment `pypi`; for a project that does not exist on PyPI yet, add it as a pending publisher. Create the `pypi` environment in the GitHub repository settings, optionally with required reviewers.
