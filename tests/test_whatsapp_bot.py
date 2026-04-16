# tests/test_whatsapp_bot.py
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from transports.whatsapp import _github_setup_requested
from core.session import IDLE, ONBOARDING_API_KEY


def _idle_session():
    return {"state": IDLE, "ctx": {"github_authed": False}}


def _authed_session():
    return {"state": IDLE, "ctx": {"github_authed": True}}


def test_github_setup_requested_connect_github():
    assert _github_setup_requested("connect github", _idle_session()) is True


def test_github_setup_requested_setup_github():
    assert _github_setup_requested("please setup github for me", _idle_session()) is True


def test_github_setup_requested_link_github():
    assert _github_setup_requested("link github", _idle_session()) is True


def test_github_setup_requested_add_github():
    assert _github_setup_requested("ADD GITHUB", _idle_session()) is True


def test_github_setup_requested_slash_github():
    assert _github_setup_requested("/github", _idle_session()) is True


def test_github_setup_requested_already_authed():
    """Does not trigger if GitHub already connected."""
    assert _github_setup_requested("connect github", _authed_session()) is False


def test_github_setup_requested_normal_message():
    assert _github_setup_requested("book a meeting", _idle_session()) is False


def test_github_setup_requested_onboarding_state():
    """Does not trigger during onboarding even if keywords present."""
    session = {"state": ONBOARDING_API_KEY, "ctx": {"github_authed": False}}
    assert _github_setup_requested("connect github", session) is False
