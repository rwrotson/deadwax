# Run Journal

Every `deadwax` call (`lookup` and `sources`) leaves a journal entry, so that a wrong match, a rejected candidate, a blocked source, or a crash can be found later and its cause read from the log.

## Files

The journal lives in the user log directory (`DEADWAX_RUNS__DIR` moves it; `DEADWAX_RUNS__ENABLED=false` turns it off):

```
<log dir>/
├── runs.jsonl                         # one summary line per run
└── runs/2026-11-13/
    └── 20261113T153012Z-a1b2c3.jsonl  # every event of that run
```

Runs older than `DEADWAX_RUNS__RETENTION_DAYS` (90; 0 keeps them forever) are deleted when a new run starts. Response bodies are not stored: each request records its size and SHA-256, and the bodies stay in the response cache until it expires. Secrets are masked in the recorded settings and removed from URLs.

## Command

```bash
deadwax runs                       # the latest 20 runs, newest first
deadwax runs --failed              # runs that did not end with a match
deadwax runs --no-match            # a source's candidate was rejected, or nothing matched
deadwax runs --source discogs      # discogs answered something other than ok
deadwax runs --kind blocked        # any source was blocked (timeout, not_found, no_match, ...)
deadwax runs -q stronger -n 50     # query or identity contains "stronger"
deadwax runs a1b2c3                # timeline of one run: start of its id or of its random suffix
deadwax runs a1b2c3 --full         # also the merges run between passes
deadwax runs a1b2c3 --format json  # the raw events
```

The timeline shows the query, the selected and skipped sources, then each pass with its context and, per source, its HTTP requests, every comparison with its artist and title scores and the checks that failed, the search hits it kept, and its outcome; then the final merge's verdict per source and the run's errors.

## Summary line

| Field | Meaning |
| --- | --- |
| `run_id`, `started_at`, `duration_ms` | identity and timing |
| `command`, `argv`, `label`, `version` | what ran |
| `outcome`, `exit_code` | `ok`, `nothing_matched`, `usage_error`, `crash`, or `interrupted` |
| `query`, `kind`, `found`, `identity` | what was asked and what was found |
| `sources` | each source's status: `ok` or an error kind (`no_match`, `blocked`, `timeout`, `not_found`, `skipped`, ...) |
| `errors`, `discrepancies`, `warnings` | reasons, disagreeing identity fields, warnings logged |
| `file` | the run's event file, relative to the journal directory |

## Events

Each event line holds `event`, `level`, `logger`, `timestamp`, `run_id`, and the `source`, `pass`, and `stage` it happened in.

| Event | Fields |
| --- | --- |
| `run.start`, `run.settings`, `query.parsed` | arguments, version, platform; settings; the parsed query |
| `lookup.selected`, `lookup.resolver`, `lookup.kind_adopted` | ready, skipped (with reasons), and unselected sources; the URL resolver; the kind it found |
| `pass.start` | sources of the pass and the context it starts from |
| `http.request` | method, URL, status, cache `hit`/`miss`/`blocked`/`off`, transports, attempts, duration, size, SHA-256, error |
| `http.retry`, `http.challenge`, `http.step_dropped` | retries with their cause and delay; bot challenges; unavailable transports |
| `match.compare` | reference and candidate (artist, title, kind, version), scores, verdict, failed checks (`artist`, `title`, `kind`) |
| `search.pick`, `search.ranked` | search hits with their verdicts and the one picked |
| `adapter.end` | outcome, errors, candidate, fact counts, duration, time waited for a slot |
| `merge.reference`, `merge.judge` | the merge's reference; verdict and scores per source |
| `run.crash`, `run.end` | traceback; the summary line and the final dossier (`DEADWAX_RUNS__DOSSIER`) |

Other library debug messages and warnings of other libraries, such as httpx, are recorded too.

## Queries

Run these in the journal directory: `~/Library/Logs/deadwax` on macOS, `~/.local/state/deadwax/log` on Linux, `%LOCALAPPDATA%\deadwax\Logs` on Windows.

```bash
# Rejected candidates and their scores, across all runs
cat runs/*/*.jsonl | jq -c 'select(.event == "match.compare" and .verdict == "no_match")
  | {source, candidate, artist_score, title_score, failed}'

# How often each source ends in each status
jq -r '.sources | to_entries[] | "\(.key) \(.value)"' runs.jsonl | sort | uniq -c | sort -rn

# Slowest requests
cat runs/*/*.jsonl | jq -c 'select(.event == "http.request") | [.duration_ms, .source, .url]' | sort -rn | head
```

## In the Library

`lookup()` never writes files. An application journals its own runs with `deadwax.logs.run_journal()`; concurrent runs in one process write separate files:

```python
from pathlib import Path

from deadwax import EntityKind, lookup, parse_query
from deadwax.logs import RunLogSettings, run_journal


async def find(text: str) -> None:
    async with run_journal(RunLogSettings(dir=Path("journal")), label="batch") as run:
        dossier = await lookup(parse_query(text, EntityKind.TRACK))
        run.record(dossier)
```

While a journal is open, the `deadwax` logger is at DEBUG and does not propagate; the application's handlers still receive the records at the level they received before. Without a journal, the same events reach the application's own logging as DEBUG records whose fields are in the `deadwax` attribute of the record (`setup_logging()` renders them).
