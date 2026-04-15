# Slack Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Slack as a full-featured power hub for bookMyCal — calendar booking and GitHub management available via `@bookMyCal` mentions in channels and DMs, with Block Kit rich formatting and interactive buttons.

**Architecture:** A new `slack_bot.py` uses Slack Bolt (async, Socket Mode) to handle `app_mention` and `message.im` events, routing through the existing `run_agent_turn` / `handle_onboarding_step` pipeline. A new `slack_formatter.py` converts agent text replies to Block Kit blocks (slot buttons, booking confirm cards, PR cards). All button actions embed the initiator's `user_id` in the button `value` field for ownership verification. No changes to existing core modules.

**Tech Stack:** `slack-bolt>=1.18` (`AsyncApp`, `AsyncSocketModeHandler`), Slack Block Kit, existing `agent.py`, `onboarding.py`, `session.py`.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `requirements.txt` | Add `slack-bolt>=1.18` |
| Modify | `.env.example` | Add `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |
| Create | `slack_formatter.py` | Pattern-detect agent reply → Block Kit JSON |
| Create | `slack_bot.py` | Bolt app, event handlers, button action handlers |
| Create | `tests/test_slack_formatter.py` | Unit tests for formatter pattern detection |
| Create | `tests/test_slack_bot.py` | Unit tests for helper functions |

---

## Task 1: Update `requirements.txt` and `.env.example`

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`

- [ ] **Step 1: Add `slack-bolt` to `requirements.txt`**

Append after the `mcp>=1.0.0` line:

```
# Slack integration (Bolt SDK — async, Socket Mode)
slack-bolt>=1.18
```

- [ ] **Step 2: Add Slack env vars to `.env.example`**

Append to `.env.example`:

```
# Slack integration (optional — only needed to run slack_bot.py)
# Create a Slack app at https://api.slack.com/apps
# Enable Socket Mode and add the scopes listed in the design doc
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-level-token
```

- [ ] **Step 3: Install the dependency**

```
cd calendar-agent && pip install "slack-bolt>=1.18"
```

Expected: installs without error.

- [ ] **Step 4: Confirm import works**

```
cd calendar-agent && python -c "from slack_bolt.async_app import AsyncApp; from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example
git commit -m "feat: add slack-bolt dependency and Slack env var template"
```

---

## Task 2: Create `slack_formatter.py`

The formatter inspects agent reply text and returns the appropriate Block Kit block list. It never calls any API — pure text-in, blocks-out.

`user_id` is embedded in button `value` fields so the bot can verify ownership when a button is clicked.

**Files:**
- Create: `slack_formatter.py`
- Create: `tests/test_slack_formatter.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_slack_formatter.py
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from slack_formatter import format_reply


def test_slot_list_returns_button_block():
    text = "2 slots available on Friday:\n1. 10:00 AM IST\n2. 2:00 PM IST"
    blocks = format_reply(text, user_id="U123")
    action_block = next(b for b in blocks if b["type"] == "actions")
    assert len(action_block["elements"]) == 2
    assert action_block["elements"][0]["action_id"] == "select_slot_1"
    assert action_block["elements"][1]["action_id"] == "select_slot_2"


def test_slot_list_embeds_user_id_in_value():
    text = "2 slots available:\n1. 10:00 AM IST\n2. 2:00 PM IST"
    blocks = format_reply(text, user_id="U999")
    action_block = next(b for b in blocks if b["type"] == "actions")
    assert action_block["elements"][0]["value"] == "U999"


def test_slot_list_includes_hint_context_block():
    text = "1 slot available:\n1. 10:00 AM IST"
    blocks = format_reply(text, user_id="U123")
    context_block = next((b for b in blocks if b["type"] == "context"), None)
    assert context_block is not None
    assert "type" in context_block


def test_booking_confirmation_returns_confirm_and_cancel_buttons():
    text = "Book 10:00 AM IST on Friday with ananya@nst.edu for 60 min. Confirm? (yes/no)"
    blocks = format_reply(text, user_id="U123")
    action_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [e["action_id"] for e in action_block["elements"]]
    assert "confirm_booking" in action_ids
    assert "cancel_booking" in action_ids


def test_booking_confirmation_embeds_user_id():
    text = "Book 10:00 AM IST. Confirm? (yes/no)"
    blocks = format_reply(text, user_id="U456")
    action_block = next(b for b in blocks if b["type"] == "actions")
    confirm_btn = next(e for e in action_block["elements"] if e["action_id"] == "confirm_booking")
    assert confirm_btn["value"] == "U456"


def test_pr_summary_returns_merge_and_comment_buttons():
    text = "PR #42: Add login flow\nStatus: 2 approvals, CI passing"
    blocks = format_reply(text, user_id="U123")
    action_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [e["action_id"] for e in action_block["elements"]]
    assert "merge_pr" in action_ids
    assert "comment_pr" in action_ids


def test_pr_summary_embeds_user_id():
    text = "PR #7: Fix typo"
    blocks = format_reply(text, user_id="U789")
    action_block = next(b for b in blocks if b["type"] == "actions")
    merge_btn = next(e for e in action_block["elements"] if e["action_id"] == "merge_pr")
    assert merge_btn["value"] == "U789"


def test_plain_text_returns_single_section_block():
    text = "Welcome to bookMyCal! Please send your Anthropic API key."
    blocks = format_reply(text)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "section"
    assert blocks[0]["text"]["text"] == text


def test_empty_text_returns_fallback_block():
    blocks = format_reply("")
    assert len(blocks) == 1
    assert blocks[0]["type"] == "section"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd calendar-agent && python -m pytest tests/test_slack_formatter.py -v
```

Expected: FAIL — `slack_formatter` module not found.

- [ ] **Step 3: Implement `slack_formatter.py`**

```python
# slack_formatter.py
import re


def format_reply(text: str, user_id: str | None = None) -> list[dict]:
    """Convert agent reply text to Slack Block Kit blocks.

    Detects the reply type by pattern matching and returns the appropriate
    Block Kit structure. Falls back to a plain text section block.

    user_id is embedded in button values so the bot can verify ownership
    when a user clicks an interactive button.
    """
    if not text:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": "_No response._"}}]

    if _is_slot_list(text):
        return _build_slot_blocks(text, user_id)
    if _is_booking_confirmation(text):
        return _build_confirm_blocks(text, user_id)
    if _is_pr_summary(text):
        return _build_pr_blocks(text, user_id)

    return _build_text_block(text)


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------

def _is_slot_list(text: str) -> bool:
    return bool(re.search(r"slots?\s+available", text, re.IGNORECASE)) or bool(
        re.search(r"^\s*1\.\s+\d{1,2}:\d{2}", text, re.MULTILINE)
    )


def _is_booking_confirmation(text: str) -> bool:
    return bool(re.search(r"(Confirm\?|yes/no)", text, re.IGNORECASE))


def _is_pr_summary(text: str) -> bool:
    return bool(re.search(r"PR #\d+", text))


# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------

def _extract_slots(text: str) -> list[str]:
    """Return slot strings from a numbered list, e.g. '1. 10:00 AM IST'."""
    return re.findall(r"^\s*\d+\.\s+(.+)$", text, re.MULTILINE)


def _build_slot_blocks(text: str, user_id: str | None) -> list[dict]:
    slots = _extract_slots(text)
    header = text.split("\n")[0]

    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": slot.strip()},
            "action_id": f"select_slot_{i + 1}",
            "value": user_id or "",
        }
        for i, slot in enumerate(slots)
    ]

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
    ]
    if buttons:
        blocks.append({"type": "actions", "elements": buttons})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "Or type a time in the chat."}],
    })
    return blocks


def _build_confirm_blocks(text: str, user_id: str | None) -> list[dict]:
    body = re.sub(r"\s*\(yes/no\)\s*", "", text).strip()

    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Confirm"},
                    "action_id": "confirm_booking",
                    "style": "primary",
                    "value": user_id or "",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Cancel"},
                    "action_id": "cancel_booking",
                    "style": "danger",
                    "value": user_id or "",
                },
            ],
        },
    ]


def _build_pr_blocks(text: str, user_id: str | None) -> list[dict]:
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔀 Merge"},
                    "action_id": "merge_pr",
                    "style": "primary",
                    "value": user_id or "",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "💬 Comment"},
                    "action_id": "comment_pr",
                    "value": user_id or "",
                },
            ],
        },
    ]


def _build_text_block(text: str) -> list[dict]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
```

- [ ] **Step 4: Run tests — all should pass**

```
cd calendar-agent && python -m pytest tests/test_slack_formatter.py -v
```

Expected: 8/8 PASS

- [ ] **Step 5: Confirm existing tests still pass**

```
cd calendar-agent && python -m pytest tests/ -v
```

Expected: all previous tests PASS

- [ ] **Step 6: Commit**

```bash
git add slack_formatter.py tests/test_slack_formatter.py
git commit -m "feat: add slack_formatter Block Kit converter"
```

---

## Task 3: Create `slack_bot.py` helper functions

These three pure functions contain the testable logic extracted from the bot event handlers. Tests run without a live Slack connection.

**Files:**
- Create: `slack_bot.py` (helpers only at this stage)
- Create: `tests/test_slack_bot.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_slack_bot.py
import os
import sys
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from session import IDLE, ONBOARDING_API_KEY, ONBOARDING_OFFICE_HOURS
from slack_bot import _is_onboarded, _extract_mention_text, _check_button_ownership


def test_is_onboarded_idle_session():
    with patch("slack_bot.get_session") as mock_get:
        mock_get.return_value = {"state": IDLE, "ctx": {}}
        assert _is_onboarded("U123") is True


def test_is_onboarded_onboarding_api_key():
    with patch("slack_bot.get_session") as mock_get:
        mock_get.return_value = {"state": ONBOARDING_API_KEY, "ctx": {}}
        assert _is_onboarded("U123") is False


def test_is_onboarded_onboarding_office_hours():
    with patch("slack_bot.get_session") as mock_get:
        mock_get.return_value = {"state": ONBOARDING_OFFICE_HOURS, "ctx": {}}
        assert _is_onboarded("U123") is False


def test_extract_mention_text_basic():
    result = _extract_mention_text("<@U012AB3CD> book 30 mins with alice", "U012AB3CD")
    assert result == "book 30 mins with alice"


def test_extract_mention_text_leading_trailing_spaces():
    result = _extract_mention_text("  <@UBOT>   hello there  ", "UBOT")
    assert result == "hello there"


def test_extract_mention_text_mention_only():
    result = _extract_mention_text("<@UBOT>", "UBOT")
    assert result == ""


def test_check_button_ownership_same_user():
    assert _check_button_ownership("U123", "U123") is True


def test_check_button_ownership_different_user():
    assert _check_button_ownership("U123", "U456") is False


def test_check_button_ownership_empty_strings():
    assert _check_button_ownership("", "") is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd calendar-agent && python -m pytest tests/test_slack_bot.py -v
```

Expected: FAIL — `slack_bot` module not found.

- [ ] **Step 3: Create `slack_bot.py` with helper functions only**

```python
# slack_bot.py
import asyncio
import logging
import os
import re

from dotenv import load_dotenv

from agent import run_agent_turn
from onboarding import handle_onboarding_step, start_for_new_user, trigger_github_setup
from session import BOOKED, get_session, reset_booking_ctx, save_session
from slack_formatter import format_reply

load_dotenv()
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_GITHUB_TRIGGER_PHRASES = {
    "/github",
    "connect github",
    "setup github",
    "link github",
    "add github",
}


def _is_onboarded(user_id: str) -> bool:
    """Return True if the user has completed onboarding (session state is not ONBOARDING_*)."""
    session = get_session(user_id)
    return not session["state"].startswith("ONBOARDING")


def _extract_mention_text(text: str, bot_user_id: str) -> str:
    """Strip the bot mention (<@BOT_USER_ID>) from message text and return clean input."""
    return re.sub(rf"<@{bot_user_id}>", "", text).strip()


def _check_button_ownership(action_user_id: str, initiator_user_id: str) -> bool:
    """Return True if the user who clicked a button is the one who initiated the flow."""
    return action_user_id == initiator_user_id
```

- [ ] **Step 4: Run tests — all should pass**

```
cd calendar-agent && python -m pytest tests/test_slack_bot.py -v
```

Expected: 9/9 PASS

- [ ] **Step 5: Run the full test suite**

```
cd calendar-agent && python -m pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add slack_bot.py tests/test_slack_bot.py
git commit -m "feat: add slack_bot helper functions with tests"
```

---

## Task 4: Complete `slack_bot.py` — event handlers and main loop

Adds the Bolt event handlers, button action handlers, modal handler, and `main()` to the existing `slack_bot.py`. No new unit tests — Bolt's async event dispatch and live Slack API calls are verified manually.

**Files:**
- Modify: `slack_bot.py`

- [ ] **Step 1: Replace `slack_bot.py` with the full implementation**

```python
# slack_bot.py
import asyncio
import logging
import os
import re

from dotenv import load_dotenv
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from agent import run_agent_turn
from onboarding import handle_onboarding_step, start_for_new_user, trigger_github_setup
from session import BOOKED, get_session, reset_booking_ctx, save_session
from slack_formatter import format_reply

load_dotenv()
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_GITHUB_TRIGGER_PHRASES = {
    "/github",
    "connect github",
    "setup github",
    "link github",
    "add github",
}

app = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN", ""))


# ---------------------------------------------------------------------------
# Pure helpers (tested in tests/test_slack_bot.py)
# ---------------------------------------------------------------------------

def _is_onboarded(user_id: str) -> bool:
    """Return True if the user has completed onboarding (session state is not ONBOARDING_*)."""
    session = get_session(user_id)
    return not session["state"].startswith("ONBOARDING")


def _extract_mention_text(text: str, bot_user_id: str) -> str:
    """Strip the bot mention (<@BOT_USER_ID>) from message text and return clean input."""
    return re.sub(rf"<@{bot_user_id}>", "", text).strip()


def _check_button_ownership(action_user_id: str, initiator_user_id: str) -> bool:
    """Return True if the user who clicked a button is the one who initiated the flow."""
    return action_user_id == initiator_user_id


# ---------------------------------------------------------------------------
# Event: @bookMyCal mention in a channel
# ---------------------------------------------------------------------------

@app.event("app_mention")
async def handle_mention(event, say, client):
    user_id = event["user"]
    thread_ts = event.get("thread_ts") or event["ts"]
    channel = event["channel"]

    bot_info = await client.auth_test()
    bot_user_id = bot_info["user_id"]
    text = _extract_mention_text(event.get("text", ""), bot_user_id)

    session = get_session(user_id)

    if not _is_onboarded(user_id):
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="Hey! You need to set up your account first. I've sent you a DM.",
        )
        dm = await client.conversations_open(users=user_id)
        dm_channel = dm["channel"]["id"]
        welcome = start_for_new_user(user_id, session)
        save_session(user_id, session)
        await client.chat_postMessage(channel=dm_channel, text=welcome)
        return

    if session["state"].startswith("ONBOARDING"):
        await say(
            text="You have an onboarding in progress. Check your DMs.",
            thread_ts=thread_ts,
        )
        return

    try:
        reply = await run_agent_turn(session, text, user_id)
        if session["state"] == BOOKED:
            reset_booking_ctx(session)
    except Exception:
        logger.exception("Agent error for user %s", user_id)
        reply = "Something went wrong. Please try again."

    save_session(user_id, session)
    blocks = format_reply(reply, user_id=user_id)
    await say(blocks=blocks, text=reply, thread_ts=thread_ts)


# ---------------------------------------------------------------------------
# Event: DM message
# ---------------------------------------------------------------------------

@app.event("message")
async def handle_dm(event, say, client):
    # Only handle DMs; ignore messages from bots (including self)
    if event.get("channel_type") != "im":
        return
    if event.get("bot_id") or event.get("subtype"):
        return

    user_id = event["user"]
    text = event.get("text", "").strip()
    if not text:
        return

    session = get_session(user_id)

    try:
        if session["state"].startswith("ONBOARDING"):
            reply = await handle_onboarding_step(session, text, user_id)
        elif (
            text.lower() in _GITHUB_TRIGGER_PHRASES
            and not session["ctx"].get("github_authed")
        ):
            reply = await trigger_github_setup(user_id, session)
        else:
            reply = await run_agent_turn(session, text, user_id)
            if session["state"] == BOOKED:
                reset_booking_ctx(session)
    except Exception:
        logger.exception("DM error for user %s", user_id)
        reply = "Something went wrong. Please try again."

    save_session(user_id, session)
    blocks = format_reply(reply, user_id=user_id)
    await say(blocks=blocks, text=reply)


# ---------------------------------------------------------------------------
# Button actions
# ---------------------------------------------------------------------------

@app.action(re.compile(r"select_slot_\d+"))
async def handle_slot_selection(ack, body, client):
    await ack()
    action = body["actions"][0]
    action_user_id = body["user"]["id"]
    initiator_user_id = action["value"]

    if not _check_button_ownership(action_user_id, initiator_user_id):
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="This isn't your booking.",
        )
        return

    slot_number = action["action_id"].split("_")[-1]
    session = get_session(action_user_id)

    try:
        reply = await run_agent_turn(session, slot_number, action_user_id)
    except Exception:
        logger.exception("Slot selection error for user %s", action_user_id)
        reply = "Something went wrong. Please try again."

    save_session(action_user_id, session)
    msg = body["message"]
    thread_ts = msg.get("thread_ts") or msg["ts"]
    blocks = format_reply(reply, user_id=action_user_id)
    await client.chat_postMessage(
        channel=body["channel"]["id"],
        thread_ts=thread_ts,
        blocks=blocks,
        text=reply,
    )


@app.action("confirm_booking")
async def handle_confirm_booking(ack, body, client):
    await ack()
    action = body["actions"][0]
    action_user_id = body["user"]["id"]
    initiator_user_id = action["value"]

    if not _check_button_ownership(action_user_id, initiator_user_id):
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="This isn't your booking.",
        )
        return

    session = get_session(action_user_id)

    try:
        reply = await run_agent_turn(session, "yes", action_user_id)
        if session["state"] == BOOKED:
            reset_booking_ctx(session)
    except Exception:
        logger.exception("Confirm booking error for user %s", action_user_id)
        reply = "Something went wrong. Please try again."

    save_session(action_user_id, session)
    blocks = format_reply(reply, user_id=action_user_id)
    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        blocks=blocks,
        text=reply,
    )


@app.action("cancel_booking")
async def handle_cancel_booking(ack, body, client):
    await ack()
    action = body["actions"][0]
    action_user_id = body["user"]["id"]
    initiator_user_id = action["value"]

    if not _check_button_ownership(action_user_id, initiator_user_id):
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="This isn't your booking.",
        )
        return

    session = get_session(action_user_id)

    try:
        await run_agent_turn(session, "no", action_user_id)
    except Exception:
        logger.exception("Cancel booking error for user %s", action_user_id)

    save_session(action_user_id, session)
    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        blocks=format_reply("Booking cancelled.", user_id=action_user_id),
        text="Booking cancelled.",
    )


@app.action("merge_pr")
async def handle_merge_pr(ack, body, client):
    await ack()
    action = body["actions"][0]
    action_user_id = body["user"]["id"]
    initiator_user_id = action["value"]

    if not _check_button_ownership(action_user_id, initiator_user_id):
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="This isn't your PR action.",
        )
        return

    session = get_session(action_user_id)

    try:
        reply = await run_agent_turn(session, "merge", action_user_id)
    except Exception:
        logger.exception("Merge PR error for user %s", action_user_id)
        reply = "Something went wrong. Please try again."

    save_session(action_user_id, session)
    blocks = format_reply(reply, user_id=action_user_id)
    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        blocks=blocks,
        text=reply,
    )


@app.action("comment_pr")
async def handle_comment_pr(ack, body, client):
    await ack()
    action_user_id = body["user"]["id"]
    initiator_user_id = body["actions"][0]["value"]

    if not _check_button_ownership(action_user_id, initiator_user_id):
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="This isn't your PR action.",
        )
        return

    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "comment_pr_submit",
            "private_metadata": body["channel"]["id"],
            "title": {"type": "plain_text", "text": "Add Comment"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "comment_block",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "comment_input",
                        "multiline": True,
                        "placeholder": {"type": "plain_text", "text": "Your comment..."},
                    },
                    "label": {"type": "plain_text", "text": "Comment"},
                }
            ],
        },
    )


@app.view("comment_pr_submit")
async def handle_comment_submit(ack, body, client, view):
    await ack()
    user_id = body["user"]["id"]
    comment_text = view["state"]["values"]["comment_block"]["comment_input"]["value"]
    channel = view["private_metadata"]

    session = get_session(user_id)

    try:
        reply = await run_agent_turn(session, f"comment: {comment_text}", user_id)
    except Exception:
        logger.exception("Comment submit error for user %s", user_id)
        reply = "Something went wrong. Please try again."

    save_session(user_id, session)
    blocks = format_reply(reply, user_id=user_id)
    await client.chat_postMessage(channel=channel, blocks=blocks, text=reply)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    bot_token = os.getenv("SLACK_BOT_TOKEN")
    app_token = os.getenv("SLACK_APP_TOKEN")

    if not bot_token:
        raise SystemExit(
            "SLACK_BOT_TOKEN is not set.\n"
            "Create a Slack app at https://api.slack.com/apps and set the token in .env"
        )
    if not app_token:
        raise SystemExit(
            "SLACK_APP_TOKEN is not set.\n"
            "Enable Socket Mode in your Slack app and set the app-level token in .env"
        )

    handler = AsyncSocketModeHandler(app, app_token)
    logger.info("bookMyCal Slack bot starting (Socket Mode)...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the unit tests to confirm helpers still pass**

```
cd calendar-agent && python -m pytest tests/test_slack_bot.py -v
```

Expected: 9/9 PASS

- [ ] **Step 3: Run the full test suite**

```
cd calendar-agent && python -m pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 4: Verify the bot file is importable without a running Slack connection**

```
cd calendar-agent && python -c "import slack_bot; print('ok')"
```

Expected: prints `ok` (the `AsyncApp` constructor accepts a placeholder token at import time).

- [ ] **Step 5: Commit**

```bash
git add slack_bot.py
git commit -m "feat: add slack_bot event handlers, button actions, and main loop"
```

---

## Spec Coverage Self-Check

| Spec requirement | Covered by |
|-----------------|-----------|
| Slack as power hub, Telegram/WhatsApp unchanged | No existing files modified |
| `@bookMyCal` mention in any channel | Task 4 — `handle_mention` |
| DM full conversation support | Task 4 — `handle_dm` |
| Per-user onboarding via DM on first mention | Task 4 — `handle_mention` (not onboarded branch) |
| Block Kit slot buttons | Task 2 — `_build_slot_blocks` |
| Block Kit booking confirmation card | Task 2 — `_build_confirm_blocks` |
| Block Kit PR card with merge + comment buttons | Task 2 — `_build_pr_blocks` |
| Comment modal on `comment_pr` click | Task 4 — `handle_comment_pr` + `handle_comment_submit` |
| Threaded channel replies (`thread_ts`) | Task 4 — all channel handlers use `thread_ts` |
| Button ownership verification | Task 3 — `_check_button_ownership`; Task 4 — all action handlers |
| Stale button ephemeral reply | Task 4 — ownership check → ephemeral message |
| Socket Mode (no public URL) | Task 1 — `slack-bolt`, `AsyncSocketModeHandler` |
| `session.py` `str` chat_id compatibility | `sanitize_chat_id` already handles Slack `user_id` strings |
| GitHub trigger phrases in DM | Task 4 — `handle_dm` (`_GITHUB_TRIGGER_PHRASES`) |
| `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` env vars | Task 1 — `.env.example`; Task 4 — `main()` validation |
