import os

from config import DEFAULT_OFFICE_START, DEFAULT_OFFICE_END

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# FSM States
ONBOARDING_API_KEY = "ONBOARDING_API_KEY"
ONBOARDING_EMAIL = "ONBOARDING_EMAIL"
ONBOARDING_OFFICE_HOURS = "ONBOARDING_OFFICE_HOURS"
ONBOARDING_WORKING_DAYS = "ONBOARDING_WORKING_DAYS"
ONBOARDING_COMPLETE = "ONBOARDING_COMPLETE"
ONBOARDING_GOOGLE_CODE = "ONBOARDING_GOOGLE_CODE"
ONBOARDING_GITHUB_PAT = "ONBOARDING_GITHUB_PAT"
IDLE = "IDLE"
SEARCHING = "SEARCHING"
AWAITING_CHOICE = "AWAITING_CHOICE"
AWAITING_CONFIRM = "AWAITING_CONFIRM"
FALLBACK_DECIDE = "FALLBACK_DECIDE"
BOOKED = "BOOKED"

def sanitize_chat_id(chat_id: int | str) -> str:
    """Return a filesystem-safe string from any chat_id type.

    Strips '@s.whatsapp.net' and leading '+' so WhatsApp JIDs become
    plain digit strings. Telegram integer IDs are simply stringified.
    """
    s = str(chat_id)
    if "@" in s:
        s = s.split("@")[0]
    s = s.lstrip("+")
    return s


_sessions: dict = {}


def _configured_google_token_path() -> str | None:
    raw = os.getenv("GOOGLE_TOKEN_PATH", "").strip()
    if not raw:
        return None
    if os.path.isabs(raw):
        return raw
    return os.path.join(_ROOT, raw)


def _google_token_available(chat_id: int | str) -> bool:
    configured = _configured_google_token_path()
    if configured and os.path.exists(configured):
        return True

    chat_path = os.path.join(
        _ROOT, ".google_tokens", f"{sanitize_chat_id(chat_id)}.json"
    )
    if os.path.exists(chat_path):
        return True

    token_dir = os.path.join(_ROOT, ".google_tokens")
    if os.path.isdir(token_dir):
        return any(name.endswith(".json") for name in os.listdir(token_dir))

    return False


def _new_session() -> dict:
    # Bootstrap from env vars if set — skips onboarding on restart
    api_key = os.getenv("ANTHROPIC_API_KEY")
    org_email = os.getenv("ORG_EMAIL")
    office_start = os.getenv("OFFICE_START", DEFAULT_OFFICE_START)
    office_end = os.getenv("OFFICE_END", DEFAULT_OFFICE_END)
    working_days_raw = os.getenv("WORKING_DAYS", "")
    working_days = [d.strip() for d in working_days_raw.split(",") if d.strip()]

    fully_configured = bool(api_key and org_email and working_days)

    return {
        "state": IDLE if fully_configured else ONBOARDING_API_KEY,
        "messages": [],
        "ctx": {
            "anthropic_api_key": api_key,
            "org_email": org_email,
            "office_hours": {
                "start": office_start,
                "end": office_end,
            },
            "working_days": working_days,
            "attendee_email": None,
            "date": None,
            "duration_mins": None,
            "proposed_slots": [],
            "chosen_slot": None,
            "delta_tried": [],
            "google_authed": False,
            "github_token": os.getenv("GITHUB_TOKEN"),
            "github_username": os.getenv("GITHUB_USERNAME"),
            "github_authed": bool(os.getenv("GITHUB_TOKEN")),
            "github_default_repos": [],
        },
    }


def get_session(chat_id: int | str) -> dict:
    key = sanitize_chat_id(chat_id)
    if key not in _sessions:
        session = _new_session()
        # Load persisted GitHub token if env var is not set
        if not os.getenv("GITHUB_TOKEN"):
            token_file = os.path.join(
                _ROOT, ".github_tokens", f"{key}.txt"
            )
            if os.path.exists(token_file):
                try:
                    with open(token_file) as f:
                        saved_token = f.read().strip()
                    if saved_token:
                        session["ctx"]["github_token"] = saved_token
                        session["ctx"]["github_authed"] = True
                except Exception:
                    pass
        _sessions[key] = session
    _sessions[key]["ctx"]["google_authed"] = _google_token_available(chat_id)
    return _sessions[key]


def save_session(chat_id: int | str, session: dict) -> None:
    _sessions[sanitize_chat_id(chat_id)] = session


def reset_session(chat_id: int | str) -> dict:
    """Full reset — re-runs onboarding."""
    key = sanitize_chat_id(chat_id)
    _sessions[key] = _new_session()
    return _sessions[key]


def reset_booking_ctx(session: dict) -> None:
    """Clear booking-specific fields but keep user preferences."""
    ctx = session["ctx"]
    ctx["attendee_email"] = None
    ctx["date"] = None
    ctx["duration_mins"] = None
    ctx["proposed_slots"] = []
    ctx["chosen_slot"] = None
    ctx["delta_tried"] = []
    session["state"] = IDLE


def reset_github_ctx(session: dict) -> None:
    """Clear GitHub auth fields."""
    ctx = session["ctx"]
    ctx["github_token"] = None
    ctx["github_username"] = None
    ctx["github_authed"] = False
    ctx["github_default_repos"] = []


def append_message(session: dict, role: str, content) -> None:
    """Append a message to the session's conversation history."""
    session["messages"].append({"role": role, "content": content})
