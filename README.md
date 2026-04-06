# bookMyCal

A conversational Telegram bot that acts as a personal calendar booking assistant and GitHub work tracker. Tell it who you want to meet and when — it checks both calendars, finds common free slots, and books the event with a Google Meet link. Ask it about your PRs, issues, and reviews — or have it manage them directly.

## Features

### Calendar
- **Conversational flow** — asks your preferences one step at a time (day, morning/afternoon, meeting name, agenda)
- **Smart slot categorisation** — separates open slots from tentative and not-yet-accepted ones
- **Name lookup** — type a name instead of a full email; the bot searches your org directory and contacts
- **Declined event handling** — treats declined events as free time, not busy
- **Google Meet** — every booking includes an auto-generated Meet link
- **Fallback scanning** — if no slot exists on the requested day, automatically tries adjusted durations and scans the rest of the week
- **Outside-org attendees** — books based on your calendar only and sends them an invite

### GitHub
- **PR management** — create PRs, submit reviews, comment, merge, close, request reviewers, set labels
- **Issue tracking** — list and view issues assigned to you or teammates
- **Standup generator** — "generate standup" produces yesterday/today/blockers from your GitHub activity
- **Plan my day** — combines calendar free blocks with GitHub action items into a prioritised schedule
- **PR detail discussion** — summarises review comments, CI failures, and merge blockers for any PR

## Tech Stack

| Layer | Tool |
|-------|------|
| Bot framework | python-telegram-bot v21 (polling) |
| AI | Anthropic Claude API (claude-opus-4-5) with tool use |
| Calendar | Google Calendar API (google-api-python-client) |
| People lookup | Google People API (org directory + contacts) |
| Auth | Google OAuth 2.0 (out-of-band flow) |
| GitHub | GitHub REST API v3 (via httpx, PAT auth) |
| Timezone | IST (Asia/Kolkata) throughout |

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/C3Suryansu/bookMyCal.git
cd bookMyCal/calendar-agent
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
5. Send `/github` to connect your GitHub account with a Personal Access Token

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Start or reset the bot |
| `/reauth` | Re-connect Google Calendar (use when scopes change) |
| `/github` | Connect or reconnect GitHub with a Personal Access Token |
| `/reset` | Clear current booking context, return to idle |
| `/status` | Show current session state and preferences |

## GitHub Setup

Send `/github` and paste a Personal Access Token with these scopes:

- `repo` — read/write access to repositories (required for PR write actions)
- `read:org` — read org membership
- `read:user` — read user profile

> For org repos with SSO or restricted PAT access, use a fine-grained token scoped to the relevant org.

## Example Usage

### Calendar booking

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

### GitHub PR management

```
You: create a PR for my feature branch
Bot: Here are the branches in owner/repo:
     1. feature/add-login
     2. fix/typo
     Which branch?

You: 1
Bot: What title for the PR?

You: Add login flow
Bot: Creating PR 'Add login flow' from feature/add-login → main. Ready to open? (yes/no)

You: yes
Bot: PR #42 opened: https://github.com/owner/repo/pull/42

You: merge it
Bot: Merge owner/repo#42 via squash? (yes/no)

You: yes
Bot: Merged. SHA: abc123
```

## Project Structure

```
calendar-agent/
├── bot.py            # Telegram bot, polling loop, command handlers
├── agent.py          # Claude API calls, tool execution
├── github_tools.py   # GitHub tool schemas, execute functions, dispatcher
├── github_utils.py   # GitHub response compression helpers
├── session.py        # In-memory session store, FSM state machine
├── onboarding.py     # Step-by-step onboarding, Google OAuth + GitHub PAT flow
├── prompts.py        # System prompt and message templates
├── calendar_utils.py # Slot intersection, IST/UTC conversion (pure functions)
├── config.py         # Constants and defaults
├── tests/            # pytest tests for GitHub tools
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── .gitignore
```

## Limitations

- Sessions are in-memory — a bot restart requires re-entering preferences (unless set in `.env`)
- Single attendee per calendar booking
- No rescheduling flow
- Local only — no deployment config
- GitHub org access requires a PAT with org-level permissions (fine-grained token for SSO orgs)
