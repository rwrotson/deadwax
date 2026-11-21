# Tests

- `tests/` mirrors the package (`core/`, `logs/`, `cli/`, `sources/` with `sources/adapters/<name>/`, `test_main.py`); `test_package.py` covers the public API, import-time behaviour, and the missing-extra message. CLI tests go through `deadwax.cli.app`.
- Tests never use the network: pytest-socket disables sockets (Unix sockets stay allowed for xdist), and source tests turn escalation off because curl_cffi opens sockets pytest-socket cannot block.
- Adapters receive their HTTP client; tests serve recorded responses from `tests/fixtures/<source>/` through `httpx.MockTransport`. `scripts/record_fixtures.py` re-records them.
- `tests/integration/` is collected only with `--live` (`poe test-live`) and checks invariants of real lookups, not exact values.
- Async tests use pytest-asyncio in strict mode.
- Tests run in parallel (pytest-xdist) and in random order (pytest-randomly); warnings are errors and each test has a 30-second timeout. Reproduce an order-dependent failure with `uv run pytest -p randomly --randomly-seed=<seed>`.
- Autouse fixtures in `conftest.py` remove `DEADWAX_*` variables, run each test in a temporary working directory (so a local `.env` is not read), and restore logging and structlog configuration.
- pytest adds its own capture handlers to the root logger, so assert on the library's handlers only.
- Test functions and fixtures need type annotations (mypy strict covers `tests/`) but no docstrings.
