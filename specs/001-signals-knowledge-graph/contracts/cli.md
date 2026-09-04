# Contract: Command-Line Interface

**Feature**: 001-signals-knowledge-graph

The agent's user-facing interface is `python -m agent`. This feature adds five flags to
`_parse_args()` in [runner.py:243-265](../../../agent/runner.py#L243-L265). No new entry point
is introduced — a separate `python -m agent.signals` would duplicate `main()`'s config loading
and error handling and fork the `--config` argument.

## Existing flags (unchanged)

| Flag | Behavior |
|---|---|
| `--dry-run` | Fetch and summarize; do not send. **Also suppresses all observation writes.** |
| `--preview` | Deliver the digest; skip mark-as-read and move-to-trash. **Does write observations.** |
| `--once` | Single poll, then exit. What the deployed launchd job passes. |
| `--config PATH` | Config file path. Default `config/newsletters.yaml`. |

## New flags

| Flag | Behavior | Exit |
|---|---|---|
| `--signals` | Generate and send a Signals Report now, bypassing the cadence check. Runs no digest. | `0` sent · `1` generation failed |
| `--signals-dry-run` | Generate a Signals Report and print a summary; send nothing. Runs no digest. | `0` generated · `1` failed |
| `--skip-signals` | Run the digest normally; never evaluate the signals cadence. | as digest |
| `--store-stats` | Print observation count, entity count, distinct senders, date range, DB size. Read-only. | `0` · `1` store unreadable |
| `--rebuild-store` | Recreate the schema after a corrupt store. **Prompts for confirmation.** | `0` · `1` declined or failed |

## Guarantees

1. **`--dry-run` never writes.** FR-008. This is the flag a user reaches for when they want to
   see what would happen, and it must not mutate durable state.
2. **`--preview` does write**, which is why the `UNIQUE` constraint exists (R-005). Preview is
   how the agent is actually run during evaluation; writes must accumulate, and re-processing
   the same emails must not inflate counts.
3. **`--rebuild-store` is the only destructive operation** and is never automatic. A corrupt
   store degrades to disabled (FR-033) and is never silently discarded (FR-034) — recovery is an
   explicit human decision, because the alternative is losing months of accumulated history to a
   transient disk error.
4. **`--signals` and `--signals-dry-run` do not run a digest.** They are diagnostic and
   iteration paths; coupling them to a fetch would consume unread emails as a side effect.
5. **Flags compose predictably**: `--skip-signals` wins over the cadence check;
   `--signals` wins over `--skip-signals` (explicit request beats blanket suppression).

## Development harness

`scripts/signals_preview.py` — not part of `python -m agent`, and required scope (R-019).

| Flag | Behavior |
|---|---|
| `--synthesize N` | Generate N days of plausible synthetic observations into a scratch DB |
| `--no-llm` | Render from computed metrics only; makes zero API calls |
| `--open` | Write rendered HTML to `test_outputs/` and open it |
| `--db PATH` | Scratch DB path. Default is a temp file. **Never `data/signals.db`.** |

`scripts/` is exempt from the Constitution V `print()` prohibition; `scripts/test_pipeline.py`
sets that precedent.
