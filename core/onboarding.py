import logging
import os
import shutil

import anthropic
import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from tools.calendar import parse_office_hours, parse_working_days
from config import DEFAULT_WORKING_DAYS, GITHUB_TOKEN_DIR
from core.prompts import (
    MSG_ASK_EMAIL,
    MSG_ASK_OFFICE_HOURS,
    MSG_ASK_WORKING_DAYS,
    MSG_ONBOARDING_START,
    MSG_READY,
)
from core.session import (
    IDLE,
    ONBOARDING_API_KEY,
    ONBOARDING_COMPLETE,
    ONBOARDING_EMAIL,
    ONBOARDING_GITHUB_PAT,
    ONBOARDING_GOOGLE_CODE,
    ONBOARDING_OFFICE_HOURS,
    ONBOARDING_WORKING_DAYS,
    sanitize_chat_id,
    save_session,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GitHub token persistence helpers
# ---------------------------------------------------------------------------

def _github_token_path(chat_id: int | str) -> str:
    """Return the file path where a user's GitHub PAT is stored."""
    os.makedirs(GITHUB_TOKEN_DIR, exist_ok=True)
    return os.path.join(GITHUB_TOKEN_DIR, f"{sanitize_chat_id(chat_id)}.txt")


def load_github_token(chat_id: int | str) -> str | None:
    """Read a persisted GitHub PAT from disk. Returns None if not found."""
    path = _github_token_path(chat_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            token = f.read().strip()
        return token if token else None
    except Exception as exc:
        logger.warning("Could not load GitHub token for %s: %s", chat_id, exc)
        return None


async def _validate_github_token(token: str) -> tuple[bool, str]:
    """
    Validate a GitHub Personal Access Token by calling GET /user.
    Returns (True, username) on success or (False, "") on failure.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10,
            )
        if resp.status_code == 200:
            username = resp.json().get("login", "")
            return True, username
        return False, ""
    except Exception as exc:
        logger.warning("GitHub token validation error: %s", exc)
        return False, ""


async def trigger_github_setup(chat_id: int | str, session: dict) -> str:
    """
    Set the session state to ONBOARDING_GITHUB_PAT and return instructions
    asking the user to paste their Personal Access Token.
    """
    session["state"] = ONBOARDING_GITHUB_PAT
    return (
        "To connect GitHub, paste your Personal Access Token (PAT) here.\n\n"
        "Create one at: https://github.com/settings/tokens/new\n\n"
        "Required scopes:\n"
        "  - repo (full repository access)\n"
        "  - read:org (read org membership)\n"
        "  - read:user (read user profile)\n\n"
        "The token starts with ghp_ or github_pat_.\n"
        "Paste it now:"
    )


def start_for_new_user(chat_id: int | str, session: dict) -> str:
    """
    Entry point for a first-time WhatsApp user.

    If the session is already fully configured (bootstrapped from env vars),
    returns MSG_READY so the bot falls through and processes the user's message.
    Otherwise returns MSG_ONBOARDING_START and leaves the session in
    ONBOARDING_API_KEY state (already set by _new_session).
    """
    if session["state"] == IDLE:
        return MSG_READY
    return MSG_ONBOARDING_START


GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/directory.readonly",       # org directory lookup
    "https://www.googleapis.com/auth/contacts.readonly",        # saved contacts
    "https://www.googleapis.com/auth/contacts.other.readonly",  # people you've emailed/met
]
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CREDENTIALS_FILE = os.path.join(_ROOT, "credentials.json")
TOKEN_DIR = os.path.join(_ROOT, ".google_tokens")

# Holds the active OAuth Flow per chat_id while awaiting the code
_pending_flows: dict[int | str, Flow] = {}


def _configured_token_path() -> str | None:
    raw = os.getenv("GOOGLE_TOKEN_PATH", "").strip()
    if not raw:
        return None
    if os.path.isabs(raw):
        return raw
    return os.path.join(_ROOT, raw)


def _token_path(chat_id: int | str) -> str:
    configured = _configured_token_path()
    if configured:
        os.makedirs(os.path.dirname(configured), exist_ok=True)
        return configured
    os.makedirs(TOKEN_DIR, exist_ok=True)
    return os.path.join(TOKEN_DIR, f"{sanitize_chat_id(chat_id)}.json")


def _legacy_token_path(chat_id: int | str) -> str:
    os.makedirs(TOKEN_DIR, exist_ok=True)
    return os.path.join(TOKEN_DIR, f"{sanitize_chat_id(chat_id)}.json")


def _seed_shared_token_from_existing(chat_id: int | str) -> None:
    configured = _configured_token_path()
    if not configured or os.path.exists(configured):
        return

    candidates: list[str] = []
    legacy_for_chat = _legacy_token_path(chat_id)
    if os.path.exists(legacy_for_chat):
        candidates.append(legacy_for_chat)

    token_files = sorted(
        (
            os.path.join(TOKEN_DIR, name)
            for name in os.listdir(TOKEN_DIR)
            if name.endswith(".json")
        ),
        key=lambda path: os.path.getmtime(path),
        reverse=True,
    ) if os.path.isdir(TOKEN_DIR) else []

    for path in token_files:
        if path not in candidates:
            candidates.append(path)

    if candidates:
        shutil.copyfile(candidates[0], configured)
        logger.info("Seeded shared Google token path %s from %s", configured, candidates[0])


async def _validate_api_key(api_key: str) -> bool:
    """Make a minimal test API call to validate the key."""
    try:
        client = anthropic.AsyncAnthropic(
            api_key=api_key,
            max_retries=1,
            timeout=15.0,
        )
        await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return True
    except anthropic.AuthenticationError:
        return False
    except Exception as exc:
        logger.warning("API key validation error: %s", exc)
        return False


def _build_auth_url(chat_id: int | str) -> str:
    """Create a Google OAuth flow and return the authorization URL."""
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"credentials.json not found at {CREDENTIALS_FILE}. "
            "Download it from Google Cloud Console (OAuth 2.0 Desktop client)."
        )
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=GOOGLE_SCOPES,
        redirect_uri="urn:ietf:wg:oauth:2.0:oob",  # out-of-band: user gets a code to paste
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    _pending_flows[sanitize_chat_id(chat_id)] = flow
    return auth_url


def _exchange_code(chat_id: int | str, code: str) -> Credentials:
    """Exchange the authorization code for credentials and save them."""
    flow = _pending_flows.get(sanitize_chat_id(chat_id))
    if not flow:
        raise ValueError("No pending OAuth flow found. Please type /start to begin again.")
    flow.fetch_token(code=code.strip())
    creds = flow.credentials
    with open(_token_path(chat_id), "w") as f:
        f.write(creds.to_json())
    del _pending_flows[sanitize_chat_id(chat_id)]
    return creds


def load_credentials(chat_id: int | str) -> Credentials | None:
    """Load saved Google credentials for a chat_id, or None if not found."""
    _seed_shared_token_from_existing(chat_id)
    path = _token_path(chat_id)
    if not os.path.exists(path):
        return None
    try:
        creds = Credentials.from_authorized_user_file(path, GOOGLE_SCOPES)
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(path, "w") as f:
                    f.write(creds.to_json())
            except Exception as exc:
                logger.warning("Could not refresh credentials for %s: %s", chat_id, exc)
        return creds
    except Exception as exc:
        logger.warning("Could not load credentials for %s: %s", chat_id, exc)
        return None


async def handle_onboarding_step(session: dict, user_text: str, chat_id: int | str) -> str:
    """
    Route the user's message through the onboarding FSM.
    Mutates session state in place.
    Returns the reply string to send to Telegram.
    """
    state = session["state"]

    if state == ONBOARDING_API_KEY:
        api_key = user_text.strip()
        valid = await _validate_api_key(api_key)
        if not valid:
            return "That key did not work. Please send a valid Anthropic API key (starts with sk-ant-)."
        session["ctx"]["anthropic_api_key"] = api_key
        session["state"] = ONBOARDING_EMAIL
        return MSG_ASK_EMAIL

    elif state == ONBOARDING_EMAIL:
        email = user_text.strip()
        session["ctx"]["org_email"] = email
        session["state"] = ONBOARDING_OFFICE_HOURS
        return MSG_ASK_OFFICE_HOURS

    elif state == ONBOARDING_OFFICE_HOURS:
        try:
            hours = parse_office_hours(user_text)
        except ValueError:
            return "I could not parse that. Please use a format like '9am to 6pm' or '09:00-18:00'."
        session["ctx"]["office_hours"] = hours
        session["state"] = ONBOARDING_WORKING_DAYS
        return MSG_ASK_WORKING_DAYS

    elif state == ONBOARDING_WORKING_DAYS:
        try:
            days = parse_working_days(user_text)
        except ValueError:
            return "I could not parse that. Try 'Mon to Fri' or 'Monday, Tuesday, Wednesday, Thursday, Friday'."
        if not days:
            days = DEFAULT_WORKING_DAYS
        session["ctx"]["working_days"] = days
        session["state"] = ONBOARDING_COMPLETE
        save_session(chat_id, session)
        return await trigger_google_auth(chat_id, session)

    elif state == ONBOARDING_GOOGLE_CODE:
        code = user_text.strip()
        try:
            _exchange_code(chat_id, code)
            session["ctx"]["google_authed"] = True
            session["state"] = IDLE
            save_session(chat_id, session)
            return "Google Calendar connected successfully!\n\n" + MSG_READY
        except Exception as exc:
            logger.error("OAuth code exchange failed: %s", exc)
            return (
                "That code did not work. Please try the link again or type /start to restart.\n"
                f"Error: {exc}"
            )

    elif state == ONBOARDING_COMPLETE:
        # User sent a message while we're still in COMPLETE — re-trigger auth
        return await trigger_google_auth(chat_id, session)

    elif state == ONBOARDING_GITHUB_PAT:
        token = user_text.strip()
        valid, github_username = await _validate_github_token(token)
        if not valid:
            return (
                "That token didn't work. Make sure it has repo, read:org, and read:user scopes.\n"
                "Try again or type /start to restart."
            )
        # Persist token to disk
        token_path = _github_token_path(chat_id)
        try:
            with open(token_path, "w") as f:
                f.write(token)
        except Exception as exc:
            logger.error("Could not save GitHub token for %s: %s", chat_id, exc)

        # Update session
        session["ctx"]["github_token"] = token
        session["ctx"]["github_username"] = github_username
        session["ctx"]["github_authed"] = True
        session["state"] = IDLE
        save_session(chat_id, session)
        return f"GitHub connected as @{github_username}. Ready."

    return "Something went wrong. Type /start to begin again."


async def trigger_google_auth(chat_id: int | str, session: dict) -> str:
    """Generate the Google OAuth URL and send instructions to the user via the return value."""
    try:
        auth_url = _build_auth_url(chat_id)
        session["state"] = ONBOARDING_GOOGLE_CODE
        save_session(chat_id, session)
        return (
            "Almost there! I need access to your Google Calendar.\n\n"
            f"1. Open this link:\n{auth_url}\n\n"
            "2. Sign in and click Allow.\n"
            "3. Google will show you a code — paste it here."
        )
    except FileNotFoundError as exc:
        logger.error("credentials.json missing: %s", exc)
        return (
            "Setup incomplete: credentials.json is missing.\n\n"
            "To fix:\n"
            "1. Go to console.cloud.google.com\n"
            "2. Create a project, enable Google Calendar API\n"
            "3. Create OAuth 2.0 credentials (Desktop app type)\n"
            "4. Download as credentials.json and place it in the bot folder\n"
            "5. Type /start to try again."
        )
    except Exception as exc:
        logger.exception("Failed to build auth URL: %s", exc)
        return "Could not start Google auth. Type /start to try again."
