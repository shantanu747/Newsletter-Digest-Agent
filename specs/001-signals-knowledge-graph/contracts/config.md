# Contract: Configuration Schema

**Feature**: 001-signals-knowledge-graph

## `config/newsletters.yaml` — three new optional top-level sections

Every section is optional. **Absent means disabled**, following the `user_profile` precedent at
[config.py:270-277](../../../agent/utils/config.py#L270-L277). A config file that predates this
feature loads and runs exactly as before (FR-035, SC-013).

```yaml
# ─── Persistent knowledge layer ───────────────────────────────
# Absent → no observations recorded, no data/ directory created.
knowledge_graph:
  enabled: true
  db_path: "data/signals.db"
  retention_days: 180          # raw observations pruned past this; rollup kept forever
  max_entities_per_idea: 8     # caps extraction output tokens

# ─── Periodic Signals Report ──────────────────────────────────
# Absent → no report is ever generated. Requires knowledge_graph.
signals:
  enabled: true
  interval_days: 3             # cost lever
  window_days: 7               # analysis window; prior window is the 7 days before it
  min_mentions: 3              # FR-014 — floor before an entity may be reported
  min_sources: 2               # FR-014 — distinct newsletters required
  max_entities_in_prompt: 40   # cost lever; keeps prompt size O(config) not O(history)
  web_search_enabled: false    # P2
  web_search_max_uses: 5       # cost lever
  model: "claude-opus-5"

# ─── Macroeconomic dashboard (P2) ─────────────────────────────
# Absent, or FRED_API_KEY unset → dashboard section renders nothing at all.
macro:
  enabled: true
  cache_hours: 12
  series:
    - T10Y3M          # 10y–3m spread — the inversion signal
    - T10Y2Y          # 10y–2y spread
    - SAHMREALTIME    # Sahm rule recession indicator
    - ICSA            # initial jobless claims
    - UNRATE          # unemployment rate
    - BAMLH0A0HYM2    # high-yield credit spread — best single stress early-warning
    - NFCI            # national financial conditions index
    - T5YIFR          # 5y forward inflation expectation
    - DFF             # effective fed funds rate
    - DTWEXBGS        # broad trade-weighted dollar
    - DEXINUS         # INR/USD
    - DCOILWTICO      # WTI crude
    - VIXCLS          # volatility
    - MORTGAGE30US    # 30-year mortgage rate
```

### Validation

Each section is parsed by a `_parse_*` helper with a `_KNOWN_*_KEYS` allowlist mirroring
`_KNOWN_SENDER_KEYS` ([config.py:28-30](../../../agent/utils/config.py#L28-L30)). An unrecognized
key raises `ConfigurationError` at load rather than being silently dropped — a typo'd
`min_sourses` that silently defaults would produce a report the user cannot explain.

Parser helpers import the logger **locally inside the function**, matching the existing
convention at [config.py:265](../../../agent/utils/config.py#L265), which exists to break an
import cycle.

### Dependency rules

- `signals` without `knowledge_graph` → `ConfigurationError`. There is nothing to analyze.
- `macro` without `signals` → warn and ignore. The dashboard has no vehicle without a report.
- `web_search_enabled: true` is independent of `macro`. Both are optional forms of grounding
  (FR-031); either, both, or neither may be on.

## Environment (`.env`)

| Variable | Required | Notes |
|---|---|---|
| `FRED_API_KEY` | **No** | Absent → `MacroSnapshot is None`, dashboard omitted, no error |

**`FRED_API_KEY` must not be added to `_REQUIRED_ENV`**
([config.py:18-26](../../../agent/utils/config.py#L18-L26)). Entries in that list raise
`ConfigurationError` when missing, so adding it would mean an existing user who pulls this change
finds their agent refusing to start — a violation of FR-035 and a direct failure of SC-013.

## `.gitignore`

Gains `data/`. The store holds a derived record of the user's reading; it is operational state,
not source.
