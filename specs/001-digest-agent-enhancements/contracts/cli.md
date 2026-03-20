# CLI Contract: Newsletter Digest Agent

**Feature**: 001-digest-agent-enhancements | **Date**: 2026-03-19

## Entry Point

```
python -m agent.runner [OPTIONS]
```

## Commands / Modes

| Mode | Flag | Description |
|------|------|-------------|
| Polling (default) | _(no flag)_ | Start continuous 4-hour polling loop; runs immediately then on interval |
| Dry run | `--dry-run` | Fetch and process emails, print digest to stdout, do not send or trash |
| Once | `--once` | Run a single poll and exit (no scheduler); useful for testing |
| Backlog | `--backlog` | Same as default but logs estimated completion time for large unread counts |

## Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--dry-run` | bool | False | Skip delivery and trash; print digest HTML to stdout |
| `--once` | bool | False | Run once and exit instead of starting scheduler |
| `--config` | path | `config/newsletters.yaml` | Path to newsletter config file |
| `--log-level` | str | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Clean exit (scheduler stopped or `--once` run completed) |
| 1 | Fatal configuration error (missing required env vars, invalid config) |
| 2 | Authentication error (invalid OAuth token, requires re-auth) |

## Environment Variables (required)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key for AI summarization |
| `GMAIL_TOKEN_PATH` | Path to `token.json` OAuth token file |
| `SMTP_USER` | Gmail address for sending digest emails |
| `SMTP_PASSWORD` | App password for SMTP auth |
| `DELIVERY_EMAIL` | Recipient address for digest emails |

## Re-authentication Notice

Upgrading from `gmail.readonly` to `gmail.modify` scope requires deleting the existing `token.json` and re-running the auth script:

```
python scripts/gmail_auth.py
```
