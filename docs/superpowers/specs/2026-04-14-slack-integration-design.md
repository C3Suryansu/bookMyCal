# Slack Integration Design

**Date:** 2026-04-14
**Project:** bookMyCal
**Scope:** Slack as primary power hub — Calendar + GitHub parity with rich Block Kit formatting, team features, and interactive components. Telegram/WhatsApp retain existing booking-only behaviour unchanged.

---

## Goals

- Let users interact with bookMyCal from Slack via DM or `@bookMyCal` mentions in channels
- Full feature parity with Telegram: calendar booking, GitHub PR management
- Slack-native experience: Block Kit cards, inline buttons, threaded replies
- Team features: PR cards with CI status, inline merge/comment buttons, channel-visible summaries
- Per-user auth (each user onboards independently via DM)

## Out of Scope

- Jira integration (next sub-project)
- Notion integration (sub-project after Jira)
- Changes to Telegram or WhatsApp behaviour
- Workspace-level shared credentials
- Webhook mode (Socket Mode only)

---

## Architecture

```
Slack Workspace
     │
     ▼
Slack Bolt (Socket Mode) — slack_bot.py
     │
     ├── Event: app_mention in channel → threaded reply
     ├── Event: message.im (DM)        → onboarding / full conversation
     ├── Action: button_click           → confirm_booking / cancel_booking / select_slot_n
     │
     ▼
slack_formatter.py
(agent text reply → Block Kit JSON)
     │
     ▼
Existing core (unchanged)
     ├── run_agent_turn      (agent.py)
     ├── handle_onboarding_step (onboarding.py)
     ├── session.py          (chat_id = Slack user_id str — already compatible)
     ├── github_tools.py
     └── calendar_utils.py
```

### New Files

| File | Responsibility |
|------|---------------|
| `slack_bot.py` | Bolt app, event handlers, button action handlers, onboarding trigger |
| `slack_formatter.py` | Converts agent text replies → Block Kit blocks |

### Existing Files Modified

| File | Change |
|------|--------|
| `requirements.txt` | Add `slack-bolt>=1.18` |
| `.env.example` | Add `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |

`session.py` requires no changes — Slack `user_id` strings (`U012AB3CD`) are already compatible with the `int | str` chat_id widening done for WhatsApp.

---

## Slack Bot (`slack_bot.py`)

### Event: `app_mention` in channel

1. Extract user text after the `@bookMyCal` mention
2. Look up session by `user_id`
3. If not onboarded → post ephemeral in channel: "Check your DMs to get set up", open DM and start onboarding
4. If onboarded → run `run_agent_turn`, format via `slack_formatter.py`, reply in thread using `thread_ts`

### Event: `message.im` (DM)

- If session state is `ONBOARDING_*` → route through `handle_onboarding_step`
- Otherwise → route through `run_agent_turn`
- Full feature parity with Telegram — DM is a complete conversation interface

### Button Actions

| Action ID | Behaviour |
|-----------|-----------|
| `confirm_booking` | Calls agent with "yes", updates block with booking confirmation |
| `cancel_booking` | Calls agent with "no", posts "Cancelled" |
| `select_slot_{n}` | Calls agent with slot number, advances to confirmation block |
| `merge_pr` | Calls agent with "merge", updates PR card |
| `comment_pr` | Prompts user for comment text via modal |

All button actions verify that `user_id` from the action matches the `user_id` who initiated the thread. Mismatched clicks get an ephemeral "This isn't your booking."

### Thread Behaviour

All channel replies use `thread_ts` from the original mention. Responses stay in thread and do not pollute the channel.

---

## Slack Formatter (`slack_formatter.py`)

Pattern-based detection on agent reply text → Block Kit JSON. Falls back to plain text block if no pattern matches.

### Slot List → Button Block

**Trigger:** reply contains "slots available" or numbered time list
**Output:** one button per slot (`select_slot_1`, `select_slot_2`, …) + "Or type a time" hint text

### Booking Confirmation → Confirm Block

**Trigger:** reply contains "Confirm?" or "yes/no"
**Output:** card with date, time, attendee, duration + `[✅ Confirm]` / `[❌ Cancel]` buttons

### PR Summary → PR Card

**Trigger:** reply contains "PR #"
**Output:** card with PR title, approval count, CI status + `[🔀 Merge]` / `[💬 Comment]` buttons

### Comment Modal

**Trigger:** user clicks `comment_pr` button
**Output:** Slack modal with a single text input ("Your comment"). On submit, calls agent with the comment text and updates the PR card.

### Plain Text

All other replies (onboarding messages, errors, general agent responses) passed through as Slack markdown text blocks with no conversion.

---

## Auth & Onboarding

**First interaction (channel mention):**
- Bot posts ephemeral visible only to that user: "Hey! You need to set up your account first. I've sent you a DM."
- Bot opens a DM and begins onboarding flow

**Onboarding flow (DM):**
Identical to Telegram/WhatsApp pipeline:
1. Anthropic API key (validated via test API call)
2. Org email
3. Office hours
4. Working days
5. Google OAuth (bot sends auth URL, user pastes code back)
6. GitHub PAT (optional, `/github` equivalent)

**Session key:** Slack `user_id` string — no changes to `session.py`

**Required env vars:**
```
SLACK_BOT_TOKEN=xoxb-...     # Bot OAuth token
SLACK_APP_TOKEN=xapp-...     # App-level token for Socket Mode
```

**Slack app configuration (manual, one-time setup):**
- Socket Mode: enabled
- OAuth scopes: `app_mentions:read`, `chat:write`, `im:read`, `im:write`, `im:history`, `channels:history`
- Event subscriptions: `app_mention`, `message.im`
- Interactivity: enabled (for button actions)

---

## Error Handling & Edge Cases

| Scenario | Behaviour |
|----------|-----------|
| Channel mention while mid-onboarding | Threaded reply: "You have an onboarding in progress. Check your DMs." |
| Button click from wrong user | Ephemeral: "This isn't your booking." |
| Button click on stale message | Ephemeral: "This has expired. Start a new request by mentioning me." |
| Claude API failure | Plain text fallback in thread: "Something went wrong, try again." |
| Google Calendar error | Descriptive error in thread |
| GitHub API error | Error surfaced in PR card or plain text |
| Socket Mode disconnect | Bolt SDK handles reconnection automatically |
| Bot mentioned in uninvited channel | Slack surfaces this natively — no custom handling needed |
| Multiple simultaneous mentions | Each handled independently; thread replies isolated by `thread_ts` |

---

## Testing Strategy

### `tests/test_slack_formatter.py`
- Slot list text → correct button block structure
- Confirmation text → correct confirm block with two buttons
- PR summary text → correct PR card block
- Plain text → passthrough as text block
- Empty reply → handled gracefully

### `tests/test_slack_bot.py`
- `_is_onboarded(user_id)` returns correct bool based on session state
- `_extract_mention_text` strips `@bookMyCal` mention from message text
- Button action ownership check — rejects clicks from wrong `user_id`
- Channel mention while mid-onboarding → correct ephemeral response

Live Slack API, Socket Mode connection, OAuth flows, and real GitHub/Calendar responses are verified manually — same philosophy as existing tests.

---

## Spec Coverage

| Requirement | Covered by |
|-------------|-----------|
| Slack as power hub, Telegram/WhatsApp unchanged | Architecture |
| Full channel bot (`@bookMyCal` in any channel) | `slack_bot.py` — `app_mention` handler |
| DM full conversation support | `slack_bot.py` — `message.im` handler |
| Per-user auth via DM onboarding | Auth & Onboarding section |
| Block Kit slot buttons | `slack_formatter.py` — slot list pattern |
| Block Kit booking confirmation | `slack_formatter.py` — confirm pattern |
| Block Kit PR cards with CI + buttons | `slack_formatter.py` — PR pattern |
| Threaded channel replies | `thread_ts` in all channel handlers |
| Button ownership verification | Button action handler |
| Stale button handling | Button action handler |
| Socket Mode (no public URL needed) | `SLACK_APP_TOKEN` + Bolt Socket Mode |
| `session.py` compatibility | `user_id` str already supported |
