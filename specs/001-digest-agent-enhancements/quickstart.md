# Quickstart: Newsletter Digest Agent Enhancements

**Date**: 2026-03-19 | **Branch**: `001-digest-agent-enhancements`

## Prerequisites

- Python 3.11+
- Existing `.env` with `ANTHROPIC_API_KEY`, `SMTP_USER`, `SMTP_PASSWORD`, `DELIVERY_EMAIL`
- Gmail OAuth set up (existing `token.json`)

## Step 1: Re-authenticate Gmail (required — scope upgrade)

The agent now needs write access to Gmail (mark as read + trash). Delete your existing token and re-authenticate:

```bash
rm token.json
cd src && python -m scripts.gmail_auth
```

Follow the browser prompt to grant the updated `gmail.modify` permission.

## Step 2: Update config/newsletters.yaml

Migrate your sender list to the new per-sender format:

```yaml
# OLD format (no longer valid):
senders:
  - "newsletter@morningbrew.com"

# NEW format:
senders:
  - address: "newsletter@morningbrew.com"
    display_name: "Morning Brew"
    mode: summarize
```

Add the three pass-through senders (update addresses to match your actual emails):

```yaml
  - address: "superhuman@mail.superhuman.com"
    display_name: "Superhuman"
    mode: pass_through

  - address: "rundown@therundown.ai"
    display_name: "The Rundown AI"
    mode: pass_through

  - address: "..."    # check your inbox for The Code's actual sender address
    display_name: "The Code"
    mode: pass_through
```

Add polling config:

```yaml
poll_interval_hours: 4
batch_size: 10
```

## Step 3: Run the agent

**Drain existing backlog (one-time)**:
```bash
cd src && python -m agent.runner --once
```

This will process all unread emails from configured senders in batches of 10, sending one digest email per batch, then trash the source emails.

**Start continuous polling**:
```bash
cd src && python -m agent.runner
```

The agent runs immediately, then polls every 4 hours. Stop with `Ctrl+C`.

**Test without sending**:
```bash
cd src && python -m agent.runner --dry-run --once
```

Prints the digest HTML to stdout without sending or trashing.

## Step 4: Verify

1. Check your delivery inbox — you should receive digest email(s)
2. Check Gmail inbox — processed source emails should be moved to trash
3. Check logs — look for `batch_delivered` and `emails_trashed` log entries

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `403 Forbidden` from Gmail API | Delete `token.json` and re-run `gmail_auth.py` |
| Sender emails not being fetched | Verify sender `address` in config matches exact From address in email headers |
| All images excluded | Expected for pass-through newsletters with no charts/graphs; check image alt text and class names in raw HTML |
| Digest not received | Check `DELIVERY_EMAIL` env var and SMTP credentials |
