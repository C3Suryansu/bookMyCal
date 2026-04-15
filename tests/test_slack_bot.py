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
