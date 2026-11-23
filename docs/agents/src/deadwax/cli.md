# CLI

- Use the public `deadwax` API and `deadwax.logs` to compose the CLI in `app.py`. Keep usage errors and lookup outcome exit codes in the command layer. Exercise command changes through `deadwax.cli.app`. See [the import rules](../../../architecture.md#r3-who-imports-what-contract).
- Keep environment and `.env` reads in `settings.load_settings()`. For new settings, add a field description and update `.env.example`. See [configuration](../../../architecture.md#configuration) and [settings and credentials](../../../../CONTRIBUTING.md#settings-and-credentials).
- Use `render.py` to dispatch output formats and render Rich output, `markdown.py` for Markdown dossiers, and `text.py` for formatting shared by both. Check the affected formats when changing output. See [the output guide](../../../output.md).
