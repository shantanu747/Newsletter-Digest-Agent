# Newsletter-Digest-Agent Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-09

## Active Technologies
- No persistent database; stateless per-run. `token.json` stores OAuth refresh token. `config/newsletters.yaml` stores non-secret configuration. (001-newsletter-digest-agent)
- Python 3.11+ + `anthropic` SDK, `google-api-python-client` + OAuth 2.0, `beautifulsoup4` + `html2text`, `APScheduler`, `Jinja2`, `PyYAML` + `python-dotenv`, `structlog`, `smtplib` (stdlib) (001-digest-agent-enhancements)
- Stateless files — `token.json` (OAuth), `config/newsletters.yaml` (config). No database. (001-digest-agent-enhancements)

- Python 3.11+ + `anthropic` SDK, `google-api-python-client` + OAuth 2.0, `beautifulsoup4`, `html2text`, `APScheduler`, `PyYAML`, `python-dotenv`, `structlog`, `Jinja2`, `pytest`, `pytest-mock`, `smtplib` (stdlib) (001-newsletter-digest-agent)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11+: Follow standard conventions

## Recent Changes
- 001-digest-agent-enhancements: Added Python 3.11+ + `anthropic` SDK, `google-api-python-client` + OAuth 2.0, `beautifulsoup4` + `html2text`, `APScheduler`, `Jinja2`, `PyYAML` + `python-dotenv`, `structlog`, `smtplib` (stdlib)
- 001-digest-agent-enhancements: Added [if applicable, e.g., PostgreSQL, CoreData, files or N/A]
- 001-newsletter-digest-agent: Added Python 3.11+ + `anthropic` SDK, `google-api-python-client` + OAuth 2.0, `beautifulsoup4`, `html2text`, `APScheduler`, `PyYAML`, `python-dotenv`, `structlog`, `Jinja2`


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
