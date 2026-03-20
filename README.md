# ai-hub

A collection of standalone tools and utilities for improving processes, productivity, and systems across the company.

Each tool lives in its own directory with its own dependencies, virtual environment, and setup instructions. There are no cross-module filesystem dependencies — any shared functionality should be published as a proper pip package.

## Tools

| Tool | Description |
|---|---|
| [oncall-triage](oncall-triage/) | Automated alert triaging agent that collects metrics, logs, and relevant code to help developers debug production issues faster |

## Adding a New Tool

1. Create a directory at the repo root (e.g. `my-tool/`)
2. Add a `pyproject.toml` with its own dependencies
3. Add a `README.md` explaining what it does and how to set it up
4. Keep it self-contained — no imports from sibling directories
