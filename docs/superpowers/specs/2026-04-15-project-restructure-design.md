# Project Restructure Design

**Date:** 2026-04-15
**Status:** Approved

## Goal

Reorganize the flat root-level Python files into logical subdirectories to improve navigability and make the architecture explicit.

## Structure

```
bookMyCal/
├── transports/             # Bot interfaces (one file per platform)
│   ├── __init__.py
│   ├── telegram.py         (was: bot.py)
│   ├── slack.py            (was: slack_bot.py)
│   ├── slack_formatter.py
│   ├── whatsapp.py         (was: whatsapp_bot.py)
│   └── whatsapp_bridge.py
├── tools/                  # External API integrations
│   ├── __init__.py
│   ├── calendar.py         (was: calendar_utils.py)
│   ├── github_tools.py
│   └── github_utils.py
├── core/                   # Agent logic and state
│   ├── __init__.py
│   ├── agent.py
│   ├── prompts.py
│   ├── session.py
│   └── onboarding.py
├── data/                   # Runtime data storage
│   ├── messages.db         (was: store/messages.db)
│   └── whatsapp.db         (was: store/whatsapp.db)
├── tests/                  # Unchanged
├── docs/                   # Unchanged
├── whatsapp-mcp/           # Unchanged (separate MCP server)
├── bookMyCal/              # Python venv (unchanged)
├── config.py               # Root-level config (unchanged)
├── credentials.json
├── requirements.txt
├── requirements-dev.txt
├── .env
└── .gitignore
```

## Import Changes

All internal imports must be updated to reflect new paths:

- `from agent import ...` → `from core.agent import ...`
- `from prompts import ...` → `from core.prompts import ...`
- `from session import ...` → `from core.session import ...`
- `from onboarding import ...` → `from core.onboarding import ...`
- `from calendar_utils import ...` → `from tools.calendar import ...`
- `from github_tools import ...` → `from tools.github_tools import ...`
- `from github_utils import ...` → `from tools.github_utils import ...`
- `from slack_formatter import ...` → `from transports.slack_formatter import ...`
- `store/` DB paths in session.py → updated to `data/`

## `config.py` DB path update

`session.py` currently references `store/` for DB paths. These must be updated to point to `data/`.

## Tests

`tests/conftest.py` and all test files that import from the old flat paths must be updated to the new package paths.

## What Does NOT Change

- `config.py` stays at root (imported by everything, simplest as a root module)
- `whatsapp-mcp/` stays at root (separate project, not a Python package)
- `bookMyCal/` venv stays at root
- `tests/` and `docs/` stay at root
