import os

from config import DEFAULT_OFFICE_START, DEFAULT_OFFICE_END

# FSM States
ONBOARDING_API_KEY = "ONBOARDING_API_KEY"
ONBOARDING_EMAIL = "ONBOARDING_EMAIL"
ONBOARDING_OFFICE_HOURS = "ONBOARDING_OFFICE_HOURS"
ONBOARDING_WORKING_DAYS = "ONBOARDING_WORKING_DAYS"
ONBOARDING_COMPLETE = "ONBOARDING_COMPLETE"
ONBOARDING_GOOGLE_CODE = "ONBOARDING_GOOGLE_CODE"
IDLE = "IDLE"
SEARCHING = "SEARCHING"
AWAITING_CHOICE = "AWAITING_CHOICE"
AWAITING_CONFIRM = "AWAITING_CONFIRM"
FALLBACK_DECIDE = "FALLBACK_DECIDE"
BOOKED = "BOOKED"

_sessions: dict = {}


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
            "google_authed": fully_configured,
        },
    }


def get_session(chat_id: int) -> dict:
    if chat_id not in _sessions:
        _sessions[chat_id] = _new_session()
    return _sessions[chat_id]


def save_session(chat_id: int, session: dict) -> None:
    _sessions[chat_id] = session


def reset_session(chat_id: int) -> dict:
    """Full reset — re-runs onboarding."""
    _sessions[chat_id] = _new_session()
    return _sessions[chat_id]


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


def append_message(session: dict, role: str, content) -> None:
    """Append a message to the session's conversation history."""
    session["messages"].append({"role": role, "content": content})
