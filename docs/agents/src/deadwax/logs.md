# Logging

- Keep logging opt-in through `setup_logging()` and use `LogSettings` for configuration. Prepare replacement handlers before changing the active configuration and preserve handlers owned by the application. See [logging setup](../../../architecture.md#logging).
- Use `run_journal()` with explicit `RunLogSettings` to record runs. Preserve event isolation between concurrent runs and restore the application's logging configuration when journaling ends. See [the run journal guide](../../../runs.md#in-the-library).
- Mask credentials in recorded settings and strip secrets from recorded URLs. Record response sizes and hashes in place of response bodies. See [the journal file format](../../../runs.md#files).
