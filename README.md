# bookMyCal

A conversational Telegram bot that acts as a personal calendar booking assistant. Tell it who you want to meet and when — it checks both calendars, finds common free slots, and books the event with a Google Meet link.

## Features

- **Conversational flow** — asks your preferences one step at a time (day, morning/afternoon, meeting name, agenda)
- **Smart slot categorisation** — separates open slots from tentative and not-yet-accepted ones
- **Name lookup** — type a name instead of a full email; the bot searches your org directory and contacts
- **Declined event handling** — treats declined events as free time, not busy
- **Google Meet** — every booking includes an auto-generated Meet link
- **Fallback scanning** — if no slot exists on the requested day, automatically tries adjusted durations and scans the rest of the week
- **Outside-org attendees** — books based on your calendar only and sends them an invite

## Tech Stack

| Layer | Tool |
|-------|------|
| Bot framework | python-telegram-bot v21 (polling) |
| AI | Anthropic Claude API (claude-opus-4-5) with tool use |
| Calendar | Google Calendar API (google-api-python-client) |
| People lookup | Google People API (org directory + contacts) |
| Auth | Google OAuth 2.0 (out-of-band flow) |
| Timezone | IST (Asia/Kolkata) throughout |

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/C3Suryansu/bookMyCal.git
cd bookMyCal
pip install -r requirements.txt
```

### 2. Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the bot token

### 3. Set up Google Cloud

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project
2. Enable these APIs:
   - Google Calendar API
   - People API
3. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
4. Application type: **Desktop app**
5. Download the JSON file and rename it to `credentials.json`, place it in the project folder
6. Go to **OAuth consent screen → Test users** and add your Google account email

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

# Optional: skip onboarding on every restart
ANTHROPIC_API_KEY=sk-ant-...
ORG_EMAIL=you@yourcompany.com
OFFICE_START=09:00
OFFICE_END=19:00
WORKING_DAYS=Monday,Tuesday,Wednesday,Thursday,Friday
```

> The Anthropic API key can also be entered via the bot's onboarding flow instead of `.env`.

### 5. Run

```bash
python bot.py
```

## First Run

1. Open your bot in Telegram and send `/start`
2. If env vars are set, you'll go straight to the ready state
3. Send `/reauth` to connect your Google Calendar (one-time OAuth step)
4. Paste the authorisation code the bot sends you back into the chat

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Start or reset the bot |
| `/reauth` | Re-connect Google Calendar (use when scopes change) |
| `/reset` | Clear current booking context, return to idle |
| `/status` | Show current session state and preferences |

## Example Usage

```
You: book 30 mins with Soumitra this week
Bot: Found Soumitra Mishra — soumitra.mishra@company.com. What day are you thinking?
     And do you prefer morning (9 AM–1 PM) or afternoon (1 PM–7 PM)?

You: Tuesday afternoon
Bot: Open slots on Tuesday, Apr 8 (afternoon):
     1. 2:00 PM - 2:30 PM IST
     2. 3:30 PM - 4:00 PM IST

     2 tentative/unaccepted slots also available — want to see those?

You: 1
Bot: What should I name this meeting?

You: Product sync
Bot: Any agenda or context to add to the invite? (or say skip)

You: discuss Q2 roadmap
Bot: Booking: Product sync on Tue Apr 8 at 2:00 PM IST with Soumitra for 30 min.
     Google Meet included. Confirm? (yes/no)

You: yes
Bot: Done. Event created.
     Meet link: https://meet.google.com/xxx-xxxx-xxx
```

## Project Structure

```
bookMyCal/
├── bot.py            # Telegram bot, polling loop, command handlers
├── agent.py          # Claude API calls, tool execution, Google Calendar/People API
├── session.py        # In-memory session store, FSM state machine
├── onboarding.py     # Step-by-step onboarding, Google OAuth flow
├── prompts.py        # System prompt and message templates
├── calendar_utils.py # Slot intersection, IST/UTC conversion (pure functions)
├── config.py         # Constants and defaults
├── requirements.txt
├── .env.example
└── .gitignore
```

## Limitations (MVP)

- Sessions are in-memory — a bot restart requires re-entering preferences (unless set in `.env`)
- Single attendee per booking
- No rescheduling flow
- Local only — no deployment config
