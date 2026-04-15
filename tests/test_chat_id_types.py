import os
import sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from session import get_session, save_session, reset_session, sanitize_chat_id


def test_sanitize_removes_domain():
    assert sanitize_chat_id("+919876543210@s.whatsapp.net") == "919876543210"


def test_sanitize_removes_plus():
    assert sanitize_chat_id("+919876543210") == "919876543210"


def test_sanitize_int_unchanged():
    assert sanitize_chat_id(123456789) == "123456789"


def test_get_session_accepts_string_jid():
    session = get_session("919876543210@s.whatsapp.net")
    assert isinstance(session, dict)
    assert "state" in session


def test_save_session_accepts_string_jid():
    session = get_session("919876543210@s.whatsapp.net")
    session["state"] = "IDLE"
    save_session("919876543210@s.whatsapp.net", session)  # must not raise


def test_reset_session_accepts_string_jid():
    session = reset_session("919876543210@s.whatsapp.net")
    assert isinstance(session, dict)


def test_get_session_same_jid_forms_return_same_session():
    """Different JID forms for the same user return the same session object."""
    # Ensure clean slate
    from session import _sessions
    for k in list(_sessions.keys()):
        if "987654" in str(k):
            del _sessions[k]

    s1 = get_session("+987654321@s.whatsapp.net")
    s2 = get_session("987654321")
    assert s1 is s2


def test_start_for_new_user_fully_configured():
    """When env vars set session to IDLE, returns MSG_READY without changing state."""
    from onboarding import start_for_new_user
    from session import IDLE
    from prompts import MSG_READY

    session = {"state": IDLE, "ctx": {"anthropic_api_key": "sk-ant-x"}}
    result = start_for_new_user("919876543210@s.whatsapp.net", session)
    assert result == MSG_READY
    assert session["state"] == IDLE


def test_start_for_new_user_needs_onboarding():
    """When session is not configured, sets state and returns onboarding start message."""
    from onboarding import start_for_new_user
    from session import ONBOARDING_API_KEY
    from prompts import MSG_ONBOARDING_START

    session = {"state": ONBOARDING_API_KEY, "ctx": {}}
    result = start_for_new_user("919876543210@s.whatsapp.net", session)
    assert result == MSG_ONBOARDING_START
    assert session["state"] == ONBOARDING_API_KEY
