# Project Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize flat Python files into `core/`, `tools/`, and `transports/` packages, and rename `store/` to `data/`.

**Architecture:** All internal imports become absolute package-prefixed paths (e.g. `from core.session import ...`). Files in `core/` that use `__file__`-relative paths to reach root-level resources (credentials, token dirs) must be updated to resolve paths via `ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`. Entry points change from `python bot.py` to `python -m transports.telegram`.

**Tech Stack:** Python, standard library `os.path`, git mv

---

### Task 1: Establish baseline — run existing tests

**Files:**
- Read: `tests/` (all)

- [ ] **Step 1: Run tests from root**

```bash
cd /Users/c3wiz/projects/bookMyCal
python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: some tests pass, some may already fail — record which ones pass now so you know what you're preserving.

- [ ] **Step 2: Commit note (no code change)**

```bash
git status
```

Expected: clean working tree (nothing to commit).

---

### Task 2: Create package directories with `__init__.py`

**Files:**
- Create: `core/__init__.py`
- Create: `tools/__init__.py`
- Create: `transports/__init__.py`
- Create: `data/` (empty dir, for DB files)

- [ ] **Step 1: Create the directories and empty `__init__.py` files**

```bash
mkdir -p /Users/c3wiz/projects/bookMyCal/core \
         /Users/c3wiz/projects/bookMyCal/tools \
         /Users/c3wiz/projects/bookMyCal/transports \
         /Users/c3wiz/projects/bookMyCal/data
touch /Users/c3wiz/projects/bookMyCal/core/__init__.py \
      /Users/c3wiz/projects/bookMyCal/tools/__init__.py \
      /Users/c3wiz/projects/bookMyCal/transports/__init__.py
```

- [ ] **Step 2: Move SQLite DBs to `data/`**

```bash
cd /Users/c3wiz/projects/bookMyCal
mv store/messages.db data/ 2>/dev/null; mv store/whatsapp.db data/ 2>/dev/null
rmdir store 2>/dev/null
ls data/
```

Expected: `data/` contains any `.db` files that existed in `store/`.

- [ ] **Step 3: Commit scaffolding**

```bash
git add core/ tools/ transports/ data/
git commit -m "chore: scaffold core/, tools/, transports/, data/ packages"
```

---

### Task 3: Move and update `core/` files (session, prompts, onboarding, agent)

**Files:**
- Move: `session.py` → `core/session.py`
- Move: `prompts.py` → `core/prompts.py`
- Move: `onboarding.py` → `core/onboarding.py`
- Move: `agent.py` → `core/agent.py`

- [ ] **Step 1: Move the files with git**

```bash
cd /Users/c3wiz/projects/bookMyCal
git mv session.py core/session.py
git mv prompts.py core/prompts.py
git mv onboarding.py core/onboarding.py
git mv agent.py core/agent.py
```

- [ ] **Step 2: Update `core/session.py` — fix `__file__`-relative paths**

`session.py` uses `os.path.dirname(__file__)` to build paths to `.google_tokens/` and `.github_tokens/`. After moving to `core/`, these must resolve to the project root.

Add near the top of `core/session.py` (after the imports):

```python
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

Then replace every occurrence of `os.path.dirname(__file__)` with `_ROOT` in `core/session.py`. There are 4 occurrences:
- Line ~42: `os.path.join(os.path.dirname(__file__), ".google_tokens", ...)` → `os.path.join(_ROOT, ".google_tokens", ...)`
- Line ~50: `os.path.join(os.path.dirname(__file__), ".google_tokens", ...)` → `os.path.join(_ROOT, ".google_tokens", ...)`
- Line ~56: `os.path.join(os.path.dirname(__file__), ".google_tokens")` → `os.path.join(_ROOT, ".google_tokens")`
- Line ~107: `os.path.join(os.path.dirname(__file__), ".github_tokens", ...)` → `os.path.join(_ROOT, ".github_tokens", ...)`

Full updated `core/session.py` top section:

```python
import os

from config import DEFAULT_OFFICE_START, DEFAULT_OFFICE_END

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# FSM States
ONBOARDING_API_KEY = "ONBOARDING_API_KEY"
# ... (rest unchanged)
```

- [ ] **Step 3: Update `core/onboarding.py` — fix imports and `__file__`-relative paths**

`onboarding.py` has these imports to update:

```python
# OLD
from calendar_utils import parse_office_hours, parse_working_days
from config import DEFAULT_WORKING_DAYS, GITHUB_TOKEN_DIR
from prompts import (MSG_ASK_EMAIL, MSG_ASK_OFFICE_HOURS, MSG_ASK_WORKING_DAYS,
                     MSG_ONBOARDING_START, MSG_READY)
from session import (IDLE, ONBOARDING_API_KEY, ONBOARDING_COMPLETE, ONBOARDING_EMAIL,
                     ONBOARDING_GITHUB_PAT, ONBOARDING_GOOGLE_CODE, ONBOARDING_OFFICE_HOURS,
                     ONBOARDING_WORKING_DAYS, sanitize_chat_id, save_session)

# NEW
from tools.calendar import parse_office_hours, parse_working_days
from config import DEFAULT_WORKING_DAYS, GITHUB_TOKEN_DIR
from core.prompts import (MSG_ASK_EMAIL, MSG_ASK_OFFICE_HOURS, MSG_ASK_WORKING_DAYS,
                           MSG_ONBOARDING_START, MSG_READY)
from core.session import (IDLE, ONBOARDING_API_KEY, ONBOARDING_COMPLETE, ONBOARDING_EMAIL,
                           ONBOARDING_GITHUB_PAT, ONBOARDING_GOOGLE_CODE, ONBOARDING_OFFICE_HOURS,
                           ONBOARDING_WORKING_DAYS, sanitize_chat_id, save_session)
```

Also fix `__file__`-relative constants in `core/onboarding.py`. Add `_ROOT` and update the two constants:

```python
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# OLD
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_DIR = os.path.join(os.path.dirname(__file__), ".google_tokens")

# NEW
CREDENTIALS_FILE = os.path.join(_ROOT, "credentials.json")
TOKEN_DIR = os.path.join(_ROOT, ".google_tokens")
```

Also update `_configured_token_path` and `_legacy_token_path` which use `os.path.dirname(__file__)`:

```python
def _configured_token_path() -> str | None:
    raw = os.getenv("GOOGLE_TOKEN_PATH", "").strip()
    if not raw:
        return None
    if os.path.isabs(raw):
        return raw
    return os.path.join(_ROOT, raw)  # was os.path.dirname(__file__)


def _legacy_token_path(chat_id: int | str) -> str:
    os.makedirs(TOKEN_DIR, exist_ok=True)
    return os.path.join(TOKEN_DIR, f"{sanitize_chat_id(chat_id)}.json")
```

- [ ] **Step 4: Update `core/agent.py` — fix imports**

```python
# OLD
from github_tools import GITHUB_TOOLS, dispatch_github_tool
from onboarding import load_credentials
from prompts import SYSTEM_PROMPT
from session import (AWAITING_CHOICE, AWAITING_CONFIRM, BOOKED, FALLBACK_DECIDE,
                     append_message, save_session)

# NEW
from tools.github_tools import GITHUB_TOOLS, dispatch_github_tool
from core.onboarding import load_credentials
from core.prompts import SYSTEM_PROMPT
from core.session import (AWAITING_CHOICE, AWAITING_CONFIRM, BOOKED, FALLBACK_DECIDE,
                           append_message, save_session)
```

`from config import ANTHROPIC_MODEL` — no change, `config.py` stays at root.

- [ ] **Step 5: Verify Python can import the core package**

```bash
cd /Users/c3wiz/projects/bookMyCal
python -c "from core.session import get_session; print('core.session OK')"
python -c "from core.prompts import SYSTEM_PROMPT; print('core.prompts OK')"
python -c "from core.onboarding import load_credentials; print('core.onboarding OK')"
```

Expected: each line prints `OK`.

- [ ] **Step 6: Commit**

```bash
git add core/
git commit -m "refactor: move session, prompts, onboarding, agent into core/"
```

---

### Task 4: Move and update `tools/` files (calendar, github)

**Files:**
- Move: `calendar_utils.py` → `tools/calendar.py`
- Move: `github_tools.py` → `tools/github_tools.py`
- Move: `github_utils.py` → `tools/github_utils.py`

- [ ] **Step 1: Move the files with git**

```bash
cd /Users/c3wiz/projects/bookMyCal
git mv calendar_utils.py tools/calendar.py
git mv github_tools.py tools/github_tools.py
git mv github_utils.py tools/github_utils.py
```

- [ ] **Step 2: Update `tools/github_tools.py` — fix imports**

```python
# OLD
from github_utils import (age_in_days, compress_issue, compress_pr,
                           compress_review_threads, get_github_headers, ...)

# NEW
from tools.github_utils import (age_in_days, compress_issue, compress_pr,
                                 compress_review_threads, get_github_headers, ...)
```

`from config import` lines in `tools/github_tools.py` — no change, `config.py` stays at root.

- [ ] **Step 3: Update `tools/calendar.py` — fix imports**

```python
# OLD (if any)
from config import FALLBACK_DELTAS_MINUTES, SLOT_GRANULARITY_MINUTES

# NEW — no change needed, config is at root
from config import FALLBACK_DELTAS_MINUTES, SLOT_GRANULARITY_MINUTES
```

No import changes needed for `tools/calendar.py` — it only imports from `config` which stays at root.

- [ ] **Step 4: Verify Python can import tools**

```bash
cd /Users/c3wiz/projects/bookMyCal
python -c "from tools.calendar import parse_office_hours; print('tools.calendar OK')"
python -c "from tools.github_utils import get_github_headers; print('tools.github_utils OK')"
python -c "from tools.github_tools import GITHUB_TOOLS; print('tools.github_tools OK')"
```

Expected: each line prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add tools/
git commit -m "refactor: move calendar_utils, github_tools, github_utils into tools/"
```

---

### Task 5: Move and update `transports/` files (telegram, slack, whatsapp)

**Files:**
- Move: `bot.py` → `transports/telegram.py`
- Move: `slack_bot.py` → `transports/slack.py`
- Move: `slack_formatter.py` → `transports/slack_formatter.py`
- Move: `whatsapp_bot.py` → `transports/whatsapp.py`
- Move: `whatsapp_bridge.py` → `transports/whatsapp_bridge.py`

- [ ] **Step 1: Move the files with git**

```bash
cd /Users/c3wiz/projects/bookMyCal
git mv bot.py transports/telegram.py
git mv slack_bot.py transports/slack.py
git mv slack_formatter.py transports/slack_formatter.py
git mv whatsapp_bot.py transports/whatsapp.py
git mv whatsapp_bridge.py transports/whatsapp_bridge.py
```

- [ ] **Step 2: Update `transports/telegram.py` — fix imports**

```python
# OLD
from agent import run_agent_turn
from onboarding import handle_onboarding_step, trigger_github_setup, trigger_google_auth
from prompts import MSG_ONBOARDING_START, MSG_READY
from session import (BOOKED, IDLE, ONBOARDING_GITHUB_PAT, get_session, reset_booking_ctx,
                     reset_github_ctx, reset_session, sanitize_chat_id, save_session)

# NEW
from core.agent import run_agent_turn
from core.onboarding import handle_onboarding_step, trigger_github_setup, trigger_google_auth
from core.prompts import MSG_ONBOARDING_START, MSG_READY
from core.session import (BOOKED, IDLE, ONBOARDING_GITHUB_PAT, get_session, reset_booking_ctx,
                           reset_github_ctx, reset_session, sanitize_chat_id, save_session)
```

Also update the `cmd_reauth` path reference (uses `os.path.dirname(__file__)` to find `.google_tokens`):

```python
# OLD (in cmd_reauth)
token_path = os.path.join(os.path.dirname(__file__), ".google_tokens", f"{sanitize_chat_id(chat_id)}.json")

# NEW
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
token_path = os.path.join(_ROOT, ".google_tokens", f"{sanitize_chat_id(chat_id)}.json")
```

Add `_ROOT` near the top of `transports/telegram.py` after imports.

- [ ] **Step 3: Update `transports/slack.py` — fix imports**

```python
# OLD
from agent import run_agent_turn
from onboarding import handle_onboarding_step, start_for_new_user, trigger_github_setup
from session import BOOKED, get_session, reset_booking_ctx, save_session
from slack_formatter import format_reply

# NEW
from core.agent import run_agent_turn
from core.onboarding import handle_onboarding_step, start_for_new_user, trigger_github_setup
from core.session import BOOKED, get_session, reset_booking_ctx, save_session
from transports.slack_formatter import format_reply
```

- [ ] **Step 4: Update `transports/whatsapp.py` — fix imports**

```python
# OLD
from agent import run_agent_turn
from onboarding import handle_onboarding_step, start_for_new_user, trigger_github_setup
from session import BOOKED, _sessions, get_session, reset_booking_ctx, save_session
from whatsapp_bridge import WhatsAppBridge

# NEW
from core.agent import run_agent_turn
from core.onboarding import handle_onboarding_step, start_for_new_user, trigger_github_setup
from core.session import BOOKED, _sessions, get_session, reset_booking_ctx, save_session
from transports.whatsapp_bridge import WhatsAppBridge
```

- [ ] **Step 5: Verify Python can import transports**

```bash
cd /Users/c3wiz/projects/bookMyCal
python -c "import transports.telegram; print('transports.telegram OK')"
python -c "import transports.slack; print('transports.slack OK')"
python -c "import transports.whatsapp; print('transports.whatsapp OK')"
```

Expected: each line prints `OK`. (These will import the bot modules without starting polling.)

- [ ] **Step 6: Commit**

```bash
git add transports/
git commit -m "refactor: move bot transports into transports/"
```

---

### Task 6: Update test imports

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_chat_id_types.py`
- Modify: `tests/test_github_write_tools.py`
- Modify: `tests/test_slack_bot.py`
- Modify: `tests/test_slack_formatter.py`
- Modify: `tests/test_whatsapp_bot.py`
- Modify: `tests/test_whatsapp_bridge.py`

- [ ] **Step 1: Update `tests/conftest.py`**

```python
import sys
import os
import pytest
from unittest.mock import patch

# Project root is one level up from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def mock_auth():
    async def _fake_auth(chat_id):
        return ("ghp_faketoken", "testuser")

    with patch("tools.github_tools._get_github_username_and_token", side_effect=_fake_auth):
        yield


@pytest.fixture
def mock_resolve_repo():
    async def _fake_resolve(token, username, repo_hint):
        return repo_hint

    with patch("tools.github_tools._resolve_repo", side_effect=_fake_resolve):
        yield
```

- [ ] **Step 2: Update `tests/test_chat_id_types.py`**

Change all imports:

```python
# OLD
from session import get_session, save_session, reset_session, sanitize_chat_id
# (inside tests)
from session import _sessions
from onboarding import start_for_new_user
from session import IDLE
from prompts import MSG_READY
from onboarding import start_for_new_user
from session import ONBOARDING_API_KEY
from prompts import MSG_ONBOARDING_START

# NEW
from core.session import get_session, save_session, reset_session, sanitize_chat_id
# (inside tests)
from core.session import _sessions
from core.onboarding import start_for_new_user
from core.session import IDLE
from core.prompts import MSG_READY
from core.onboarding import start_for_new_user
from core.session import ONBOARDING_API_KEY
from core.prompts import MSG_ONBOARDING_START
```

- [ ] **Step 3: Update `tests/test_github_write_tools.py`**

```python
# OLD
from github_tools import _list_branches
from github_tools import _execute_github_create_pr
from github_tools import _execute_github_pr_submit_review
from github_tools import _execute_github_pr_comment
from github_tools import _execute_github_pr_merge
from github_tools import _execute_github_pr_close
from github_tools import _execute_github_pr_request_reviewers
from github_tools import _execute_github_pr_set_labels

# NEW — replace every `from github_tools import` with `from tools.github_tools import`
from tools.github_tools import _list_branches
from tools.github_tools import _execute_github_create_pr
from tools.github_tools import _execute_github_pr_submit_review
from tools.github_tools import _execute_github_pr_comment
from tools.github_tools import _execute_github_pr_merge
from tools.github_tools import _execute_github_pr_close
from tools.github_tools import _execute_github_pr_request_reviewers
from tools.github_tools import _execute_github_pr_set_labels
```

- [ ] **Step 4: Update `tests/test_slack_bot.py`**

```python
# OLD
from session import IDLE, ONBOARDING_API_KEY, ONBOARDING_OFFICE_HOURS
from slack_bot import _is_onboarded, _extract_mention_text, _check_button_ownership

# NEW
from core.session import IDLE, ONBOARDING_API_KEY, ONBOARDING_OFFICE_HOURS
from transports.slack import _is_onboarded, _extract_mention_text, _check_button_ownership
```

- [ ] **Step 5: Update `tests/test_slack_formatter.py`**

```python
# OLD
from slack_formatter import format_reply

# NEW
from transports.slack_formatter import format_reply
```

- [ ] **Step 6: Update `tests/test_whatsapp_bot.py`**

```python
# OLD
from whatsapp_bot import _github_setup_requested
from session import IDLE, ONBOARDING_API_KEY

# NEW
from transports.whatsapp import _github_setup_requested
from core.session import IDLE, ONBOARDING_API_KEY
```

- [ ] **Step 7: Update `tests/test_whatsapp_bridge.py`**

```python
# OLD
from whatsapp_bridge import WhatsAppBridge

# NEW
from transports.whatsapp_bridge import WhatsAppBridge
```

- [ ] **Step 8: Commit**

```bash
git add tests/
git commit -m "refactor: update test imports for new package structure"
```

---

### Task 7: Run full test suite and fix any remaining issues

**Files:**
- Read: any failing test output

- [ ] **Step 1: Run all tests**

```bash
cd /Users/c3wiz/projects/bookMyCal
python -m pytest tests/ -v 2>&1
```

Expected: same tests that passed in Task 1 still pass. No new failures.

- [ ] **Step 2: If any tests fail due to import errors, fix them**

For each `ModuleNotFoundError`, check whether the import was missed in Tasks 3-6 and apply the appropriate fix from the relevant task above.

Run again after fixing:

```bash
python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: PASSED count matches or exceeds baseline from Task 1.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "refactor: restructure project into core/, tools/, transports/ packages"
```

---

## Running the bots after this change

| Before | After |
|--------|-------|
| `python bot.py` | `python -m transports.telegram` |
| `python slack_bot.py` | `python -m transports.slack` |
| `python whatsapp_bot.py` | `python -m transports.whatsapp` |
