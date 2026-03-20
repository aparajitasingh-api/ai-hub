# oncall-triage

Automated oncall alert triaging agent. Receives Datadog alert webhooks, pulls metrics and logs for the alert window, posts a consolidated report to Google Chat, then runs an RCA analysis against the relevant codebase on GitHub.

## How It Works

1. Datadog fires a webhook on alert trigger
2. Agent fetches metric data (Datadog API) and logs (Elasticsearch) for the alert timeframe +/- 10 minutes
3. A triage report is posted to a Google Chat space as a new thread
4. An RCA agent searches GitHub for related code, correlates it with the error signals, and posts its analysis as a reply in the same thread

## Quick Start

```bash
cd oncall-triage
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in your credentials
python -m src.main
```

See [SETUP.md](SETUP.md) for full setup instructions (Datadog webhook config, Elasticsearch access, Google Chat webhook, GitHub token).

## Tests

```bash
pytest tests/ -v
```
