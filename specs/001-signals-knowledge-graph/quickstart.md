# Quickstart: Signals Report

**Feature**: 001-signals-knowledge-graph | **Date**: 2026-09-03

Two audiences: the developer implementing this (who needs to see the feature before real history
exists), and the reader turning it on.

---

## For the implementer — see it working on day one

A fresh install has zero history, so the honest report is empty for a week. Do not implement
against an empty store; you cannot tune a prompt or lay out a template with nothing in it.

```bash
# 1. Establish the green baseline BEFORE writing any code
pytest

# 2. Populate a scratch database with 30 days of synthetic observations
python scripts/signals_preview.py --synthesize 30

# 3. Render from computed metrics only — zero API calls, exercises metrics.py end-to-end
python scripts/signals_preview.py --no-llm

# 4. Full report with the real analysis call, written to test_outputs/ and opened
python scripts/signals_preview.py --open
```

Steps 2 and 3 are free and fast. Most of the metrics work can be finished without ever calling
the API.

---

## Verification sequence

Run in order. Each step checks something a later step would hide.

```bash
# Existing suite still green, and the new config gates leave it inert
pytest

# Daily digest unchanged with the feature disabled, and no data/ directory created  [SC-001]
python -m agent --dry-run
test ! -d data/ && echo "PASS: no data/ created while disabled"

# Metrics correct without any API call
python scripts/signals_preview.py --synthesize 30 --no-llm

# End-to-end signals path, nothing sent
python -m agent --signals-dry-run

# Idempotency  [SC-002] — the number must not change
python -m agent --preview
sqlite3 data/signals.db "select count(*) from observation"
python -m agent --preview
sqlite3 data/signals.db "select count(*) from observation"   # ← must be identical

# Degradation  [SC-007] — digest still ships over a corrupt store
cp data/signals.db data/signals.db.bak
echo "garbage" > data/signals.db
python -m agent --dry-run     # must complete normally, log the failure, not raise
mv data/signals.db.bak data/signals.db

# Quiet-day cadence  [SC-006] — report fires with zero unread newsletters
python -m agent --signals-dry-run

# Standing polish pair
pytest && ruff check .
```

The idempotency check is the one most worth running twice. It is the difference between a trend
report and a fabricated-acceleration generator.

---

## For the reader — turning it on

### Step 1 — enable memory (P1)

Add to `config/newsletters.yaml`:

```yaml
knowledge_graph:
  enabled: true

signals:
  enabled: true
  interval_days: 3
```

That is the minimum. Everything else has a default.

Nothing changes in your daily digest. The agent starts recording what each idea is about.

### Step 2 — wait

The first report needs roughly two analysis windows (about two weeks at the default settings)
before its trends mean anything. Reports generated before then say so explicitly — a cold-start
label, not a broken-looking empty page.

To see the shape of the report immediately without waiting:

```bash
python -m agent --signals-dry-run
```

### Step 3 — add external grounding (P2, optional)

Get a free FRED API key at <https://fred.stlouisfed.org/docs/api/api_key.html> and add to `.env`:

```bash
FRED_API_KEY=your_key_here
```

Then in `config/newsletters.yaml`:

```yaml
macro:
  enabled: true

signals:
  web_search_enabled: true
```

The macro dashboard and web search are independent. Either, both, or neither.

### Turning it off

Delete the `signals:` section and reports stop. Delete `knowledge_graph:` and recording stops
too — the daily digest returns to exactly its previous behavior. The database is left in place;
nothing deletes your history but you.

---

## Cost

| Component | Frequency | Approximate monthly |
|---|---|---|
| Entity extraction | folded into existing calls | ~$0.80 |
| Trend analysis | every 3 days | ~$1.50 |
| Web search | ≤5 per report | ~$0.30 |
| Macro data | free | $0.00 |
| | | **~$2.60** |

Three levers if that is too much: raise `interval_days`, lower `max_entities_in_prompt`, lower
`web_search_max_uses` (FR-051).

---

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| No report arriving | Interval not elapsed, or `signals.enabled: false` | `python -m agent --store-stats` |
| Report says cold start | Fewer than 2 windows of history | Expected. Wait, or use `--signals-dry-run` |
| Report sections empty | Nothing cleared `min_mentions` × `min_sources` | Normal on a quiet week. Lower `min_sources` only if you accept single-source noise |
| `store_disabled` in logs | Corrupt or unreadable database | `python -m agent --rebuild-store` (destroys history — check disk and permissions first) |
| Macro dashboard missing | `FRED_API_KEY` unset or `macro.enabled: false` | Expected behavior, not an error |
| Counts look inflated | Should be impossible — `UNIQUE` constraint | File it; the constraint has failed |
