# Contributing

Layers, import rules, the lookup flow, and errors are described in the [architecture guide](docs/architecture.md); agent workflow in [`AGENTS.md`](AGENTS.md).

## Checks

- Run `uv run poe check` after code changes. After documentation, `properdocs.yml`, or public docstring changes, also run `uv run --group docs properdocs build --strict`.
- Use non-rewriting checks (`poe fmt-check`, `poe lint`) for verification; run formatters or `--fix` only when intentionally editing files. Pre-commit's Ruff hooks rewrite files.
- `poe test-fast` skips coverage. CI also runs tests on macOS, the lowest-dependency job, package and docs builds, and security scans.
- Do not lower coverage thresholds, disable checks, relax import-linter contracts, or add lint and type suppressions solely to pass CI. Explain necessary suppressions at the affected line.
- MyPy runs with `strict = true` and the Pydantic plugin over `src/`, `tests/`, and `docs/`. All code has complete type annotations; prefer `X | Y` over `Optional[X]`.

## Dependencies

- Put runtime imports needed by the core in `[project].dependencies` and those of outer layers in their extra; also list extra packages in the `dev` group so tests can import them. Put development tools in the `dev` group and documentation tools in the `docs` group.
- Keep runtime dependencies minimal and lower bounds wide enough for library consumers; they share one environment with the application.
- Change dependencies through uv (`uv add`, `uv remove`) so `pyproject.toml` and `uv.lock` change together. Verify the lock with `uv sync --locked --all-groups`.
- Raise a direct dependency's lower bound when code needs a newer API. The locked environment does not check lower bounds; the CI `lowest` job does.
- Do not import packages that are installed only as transitive dependencies.
- Add a new third-party dependency to the lowest layer that needs it and to that layer's extra (none for `core`), and update the import-linter contract that lists the layer's allowed packages.
- Security floors for transitive dependencies go in `[tool.uv] constraint-dependencies`.
- Use the project environment for tools. Do not install packages manually into `.venv`.

## Library Functionality and Public API

- Put it in the right layer, export public names from `core/__init__.py` (or `sources/__init__.py`) and `deadwax/__init__.py` (`__all__`), test it in the mirrored `tests/` directory, and list the module in `docs/reference/index.md`.
- To expose it on the command line, change `src/deadwax/cli/app.py` and test it in `tests/cli/`.
- Subclass a built-in exception as well as `DeadwaxError` when callers would reasonably catch it (`InvalidQueryError` is also a `ValueError`).
- When changing settings, the public API, or the command, update `.env.example`, README, and the docs.

## Settings and Credentials

- `src/deadwax/cli/settings.py` defines the command's `Settings`. Every setting needs a `Field(description=...)` and a line in `.env.example`; `tests/cli/test_settings.py` enforces both.
- A setting that holds a credential (token, API key, client ID or secret) gets step-by-step instructions for obtaining it in README's "Credentials" section, in the same change.
- Do not edit generated pages (configuration, schema, API reference); edit `Settings` field descriptions and source docstrings instead.

## Documentation and Comments

- Write documentation, docstrings, and comments in English. Keep them short and factual. Describe each entity's purpose without editorial commentary or tutorials.
- Do not add module docstrings. Package docstrings in `__init__.py` are optional. Put package behavior and important module details in Markdown documentation such as `README.md` or `docs/`.
- Give public classes, functions, and ordinary methods a docstring. Prefer one line describing their overall purpose; do not repeat names, signatures, or type annotations. Ruff checks these in library code. Test functions, fixtures, and standard `dunder` methods are exempt.
- Add docstrings to protected or private objects only when they explain behavior that is not clear from code.
- Keep inline comments only for non-obvious behavior or decisions. Put a short comment on the relevant line when it fits; otherwise place it immediately above. Retain necessary tool directives such as `# noqa` and `# type: ignore`.
- A comment placed above a line or group of lines applies only to it. Separate that line or group from the code before and after it with a blank line, unless it starts or ends a block, so the comment's scope is clear. At module and class level, give each commented constant or attribute its own block, and keep uncommented related definitions together in one block.
- At module level, keep `UPPER_CASE` constants and lowercase objects (loggers, imported modules, apps, CLI runners) in separate blocks divided by a blank line.
- In long functions, methods, and tests, separate logical steps (input validation, setup, command building, execution, result handling; arrange, act, assert) with a single blank line. Do not add comments to label the steps. Keep short functions compact.
- Follow the [Python formatting rules in `AGENTS.md`](AGENTS.md#python-formatting) for line wrapping and trailing commas.
- Prefer clearer names and more precise types over comments that restate code.

## Commits and Versioning

- Commits follow [Conventional Commits](https://www.conventionalcommits.org/); the `commit-msg` hook checks the format. Install hooks with `uv run pre-commit install`.
- Mark removals and incompatible public API changes with `!` or a `BREAKING CHANGE:` footer so Commitizen bumps the version correctly.
- `uv run cz bump` bumps the version, updates `CHANGELOG.md`, and tags the release; `uv run cz changelog` updates only the changelog.
