# WhatsApp Integration — Design Spec
Date: 2026-04-07

## Overview

Add WhatsApp as a second transport for the bookMyCal bot. The same calendar booking and GitHub management capabilities available via Telegram become available via WhatsApp. Both bots run simultaneously; each is started independently (`python bot.py` / `python whatsapp_bot.py`).

The integration uses the [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) Go bridge, which connects to WhatsApp Web via QR code and exposes MCP tools. `whatsapp_bot.py` spawns the bridge as a subprocess and communicates via the MCP stdio protocol using the `mcp` Python SDK.

---

## Architecture

No shared state between the two bots. Each maintains its own in-memory sessions keyed by transport-specific IDs (Telegram integer `chat_id` vs WhatsApp JID string).

### New files

**`whatsapp_bridge.py`** — MCP client wrapper. Owns the subprocess lifecycle for the Go binary. Exposes two async methods to the rest of the bot:
- `poll_messages(after_timestamp: float) -> list[dict]` — calls the MCP `list_messages` tool and returns new incoming DMs (filters out group chats and self-messages)
- `send_message(jid: str, text: str) -> None` — calls the MCP `send_message` tool

**`whatsapp_bot.py`** — main polling loop. Mirrors `bot.py` in structure: starts the bridge, runs a 2-second asyncio poll loop, routes each message through the existing `run_agent_turn` or `handle_onboarding_step`, sends the reply. No Telegram dependency.

### Modified files

**`session.py`** — widen `chat_id` type from `int` to `int | str` in all function signatures (`get_session`, `save_session`, `reset_session`). The internal `_sessions: dict` already accepts any key. The GitHub token file path uses a sanitised version of the chat_id (strip `@s.whatsapp.net`, replace `+` with empty string) to avoid filesystem special-character issues.

**`onboarding.py`** — add `start_for_new_user(chat_id: int | str, session: dict) -> str`. Called by `whatsapp_bot.py` when it sees a JID for the first time. Behaves identically to `cmd_start` in `bot.py`: if fully configured → returns `MSG_READY`, otherwise → returns `MSG_ONBOARDING_START` and sets state to `ONBOARDING_API_KEY`.

**`requirements.txt`** — add `mcp>=1.0.0`

**`.env.example`** — add `WHATSAPP_MCP_BINARY=` entry with a comment

---

## Message Flow

```
python whatsapp_bot.py
  → WhatsAppBridge.connect()
      → spawns Go binary at $WHATSAPP_MCP_BINARY
      → MCP initialize handshake
      → first run: prints QR code to terminal; user scans with WhatsApp
      → authenticated (bridge persists session to disk)

asyncio loop (every 2 seconds):
  messages = bridge.poll_messages(after_timestamp=last_poll_time)

  for msg in messages:
    skip if msg.from_group          # JID ends in @g.us
    skip if msg.from_self           # our own JID

    session = get_session(msg.sender_jid)

    if msg.sender_jid not in seen_jids:
        welcome = start_for_new_user(msg.sender_jid, session)
        seen_jids.add(msg.sender_jid)
        await bridge.send_message(msg.sender_jid, welcome)
        if session["state"].startswith("ONBOARDING"):
            continue   # wait for onboarding response before processing message
        # IDLE: fall through and process the user's first message normally

    if session["state"].startswith("ONBOARDING"):
        reply = await handle_onboarding_step(session, msg.text, msg.sender_jid)

    elif github_setup_requested(msg.text, session):
        reply = await trigger_github_setup(msg.sender_jid, session)

    else:
        reply = await run_agent_turn(session, msg.text, msg.sender_jid)
        if session["state"] == BOOKED:
            reset_booking_ctx(session)

    save_session(msg.sender_jid, session)
    await bridge.send_message(msg.sender_jid, reply)
```

**`github_setup_requested(text, session)`** — returns `True` when `github_authed` is False AND the message contains any of: `"connect github"`, `"setup github"`, `"link github"`, `"add github"`, `"/github"` (case-insensitive). This replaces the `/github` command.

---

## Onboarding

WhatsApp has no slash commands. Onboarding is fully conversational:

- First message from a new JID auto-triggers `start_for_new_user`
- If env vars (`ANTHROPIC_API_KEY`, `ORG_EMAIL`, `WORKING_DAYS`) are set → goes straight to IDLE
- If not set → walks through the same text-based steps as Telegram (API key → email → office hours → working days → Google OAuth)
- GitHub PAT setup is triggered by the user saying "connect my github" or similar phrases

All existing onboarding steps in `onboarding.py` are already text-based and work without modification; only the entry point is new.

---

## Filtering

- **Group chats excluded**: JIDs ending in `@g.us` are skipped entirely
- **Self-messages excluded**: bridge returns the bot's own JID on connect; messages from that JID are skipped
- **Only text messages**: non-text messages (images, voice notes) are skipped with no reply

---

## Error Handling

- Follows the same pattern as `bot.py`: wrap each message handler in try/except, send "Something went wrong. Please try again." on unhandled exceptions
- If the MCP bridge subprocess crashes: log the error and attempt to restart it (one retry with 5-second delay; exit if retry fails)
- Bridge connection errors on startup: print a clear message and exit with code 1

---

## Setup Instructions (user-facing)

1. Clone and build the Go bridge:
   ```bash
   git clone https://github.com/lharries/whatsapp-mcp
   cd whatsapp-mcp
   go build -o whatsapp-mcp-server ./...
   ```
2. Add to `.env`:
   ```
   WHATSAPP_MCP_BINARY=/path/to/whatsapp-mcp-server
   ```
3. Install new dependency:
   ```bash
   pip install -r requirements.txt
   ```
4. Run:
   ```bash
   python whatsapp_bot.py
   ```
   Scan the QR code printed to the terminal with WhatsApp (Settings → Linked Devices). Authentication is persisted — QR scan is one-time.

---

## Out of Scope

- Group chat support
- Media/voice message handling
- Status updates
- WhatsApp Business API (uses unofficial WhatsApp Web only)
- Shared session state between Telegram and WhatsApp transports
