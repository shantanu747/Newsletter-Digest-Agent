# Research: Newsletter Digest Agent Enhancements

**Phase**: 0 | **Date**: 2026-03-19 | **Branch**: `001-digest-agent-enhancements`

---

## Decision 1: Gmail OAuth Scope Upgrade

**Decision**: Upgrade OAuth scope from `gmail.readonly` to `gmail.modify`

**Rationale**: Both "mark as read" and "move to trash" use `messages.modify()` which requires the `gmail.modify` scope. Gmail has no separate `gmail.trash` scope — trash is implemented as label manipulation (adding the `TRASH` label). The `gmail.modify` scope is a superset of `gmail.readonly`, so all existing read operations continue to work unchanged.

**Impact**: Users must re-authenticate once after this change to grant the new permission. The existing `token.json` will be invalid for write operations and will trigger a re-auth flow automatically.

**Alternatives considered**: Using `gmail.labels` scope (insufficient — doesn't cover message body reads) or keeping `gmail.readonly` and managing state externally (rejected — breaks the trash workflow).

---

## Decision 2: Gmail API Methods

**Decision**: Use `messages.modify()` for both mark-as-read and trash operations.

**Mark as read**:
```
service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']})
```

**Move to trash**:
```
service.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': ['TRASH']})
```

**Rationale**: Single unified method for label manipulation. Low risk — Gmail quota is 1,000,000 modify calls/day vs. ~100 emails per poll. No rate limiting needed for Gmail API writes.

**Alternatives considered**: `messages.trash()` API method exists but is equivalent to `addLabelIds: ['TRASH']` and less flexible.

---

## Decision 3: Unread Email Query

**Decision**: Server-side Gmail query combining sender list, unread status, and inbox location.

**Query format**:
```
from:(sender1@example.com OR sender2@example.com) is:unread in:inbox
```

**Rationale**: Filters server-side (not client-side) reducing bandwidth and latency. Existing `GmailFetcher` already supports pagination via `nextPageToken` — the same pattern handles large result sets. The `in:inbox` clause prevents accidentally processing emails in spam or trash.

**Alternatives considered**: Time-bounded query (`after:epoch`) — rejected because requirement is "all unread regardless of age", not time-bounded.

---

## Decision 4: APScheduler Polling Pattern

**Decision**: Replace `CronTrigger` with `IntervalTrigger(hours=poll_interval_hours)` and run job immediately on startup.

**Pattern**:
```python
trigger = IntervalTrigger(hours=config.poll_interval_hours)
scheduler.add_job(run_poll, trigger=trigger)
run_poll()          # immediate first execution
scheduler.start()   # then every 4 hours
```

**Rationale**: `IntervalTrigger` is designed for "every N hours" patterns. Running the job directly before `scheduler.start()` achieves "run now + every 4 hours" without `misfire_grace_time` complexity. Existing exception handling (catch known errors, log, continue) is already production-ready for background jobs.

**Alternatives considered**: `CronTrigger` (existing) — time-of-day based, not interval-based; doesn't support "run immediately"; rejected.

---

## Decision 5: Image Classification Heuristics (Priority Order)

**Decision**: Layer four HTML signal checks, applied in priority order. First exclusion match wins.

**Signal priority stack** (highest confidence first):

| Priority | Signal | Exclude if | Include if |
|----------|--------|-----------|-----------|
| 1 | Known tracking domain | In exclusion domain list | In trusted CDN list |
| 2 | Image dimensions | width ≤ 1 AND height ≤ 1 (tracking pixel) | — |
| 3 | CSS class / ID names | Contains: `banner`, `header`, `logo`, `icon`, `social`, `ad`, `promo`, `footer`, `brand`, `sponsor` | — |
| 4 | Parent element tag | Parent is `<header>`, `<footer>`, `<nav>` | Parent is `<article>`, `<section>`, `<p>`, `<main>` |
| 5 | Alt text keywords | Alt contains: `logo`, `icon`, `badge`, `banner`, `social` | Alt contains: `chart`, `graph`, `data`, `visualization`, `meme` |
| 6 | Aspect ratio + size | Width < 100px AND aspect ratio 0.8–1.2 (square) | Width ≥ 200px AND landscape or portrait |
| 7 | Default | Exclude (exclude-by-default policy) | — |

**Rationale**: HTML context heuristics only (no AI vision calls per spec decision Q1). Exclude-by-default policy means false negatives (missing a real chart) are preferred over false positives (showing a banner). Layers 3 and 4 (class names and parent element) close the main gaps in the current implementation.

**Current code gaps addressed**:
- Current: only tracks tracking domains + width ≥ 50px threshold
- New: adds class/id name filtering, parent element check, alt text analysis, aspect ratio

**Alternatives considered**: AI vision per image (rejected per spec clarification Q1); only width threshold (insufficient — logos can be 200px wide).

---

## Decision 6: Pass-Through Content Preservation

**Decision**: Use `html2text` with structure-preserving settings on the filtered HTML body, then truncate at 500 words at the nearest sentence boundary.

**Rationale**: Existing `EmailParser` already uses `html2text` for conversion. For pass-through content, the key is to NOT strip structural elements (headings, bullets, numbered lists) before conversion. The current parser strips boilerplate aggressively — pass-through mode needs a lighter-touch pipeline that preserves the newsletter's own structure.

**Alternatives considered**: Render HTML directly in the digest template (rejected — digest template uses plaintext summaries; mixing raw HTML and template HTML is fragile).

---

## Decision 7: Batch State Tracking (No Persistent State File)

**Decision**: No persistent state file needed. Use Gmail email labels (read/unread) as the source of truth.

**Rationale**: Per spec clarification Q2, emails are marked as read in Gmail immediately after successful delivery. If the agent restarts mid-run, the next poll will only pick up emails that are still unread — already-delivered batches are naturally excluded because their source emails are now read. No separate run-state file needed. This is consistent with the existing "stateless per-run" architecture principle in CLAUDE.md.

**Alternatives considered**: Local `processed_ids.json` file (rejected — adds statefulness complexity, risks stale state if file is deleted or corrupted).
