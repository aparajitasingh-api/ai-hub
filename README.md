# ai-hub

A collection of standalone tools and utilities for improving processes, productivity, and systems across the company.

Each tool lives in its own directory with its own dependencies and setup instructions. There are no cross-module filesystem dependencies — any shared functionality should be published as a proper package dependency.

## Tools

| Tool | Description |
|---|---|
| [oncall-triage](oncall-triage/) | Automated alert triaging agent that collects metrics, logs, and relevant code to help developers debug production issues faster |
| [spec-library](spec-library/) | Service specification registry that discovers and serves monitoring/oncall metadata from across the org's GitHub repos |

## Adding a New Tool

1. Create a directory at the repo root (e.g. `my-tool/`)
2. Add a `pyproject.toml` (Python) or `go.mod` (Go) with its own dependencies
3. Add a `README.md` explaining what it does and how to set it up
4. Keep it self-contained — no filesystem imports from sibling directories; shared dependencies go through proper package managers
