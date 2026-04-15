import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from slack_formatter import format_reply


def test_slot_list_returns_button_block():
    text = "2 slots available on Friday:\n1. 10:00 AM IST\n2. 2:00 PM IST"
    blocks = format_reply(text, user_id="U123")
    action_block = next(b for b in blocks if b["type"] == "actions")
    assert len(action_block["elements"]) == 2
    assert action_block["elements"][0]["action_id"] == "select_slot_1"
    assert action_block["elements"][1]["action_id"] == "select_slot_2"


def test_slot_list_embeds_user_id_in_value():
    text = "2 slots available:\n1. 10:00 AM IST\n2. 2:00 PM IST"
    blocks = format_reply(text, user_id="U999")
    action_block = next(b for b in blocks if b["type"] == "actions")
    assert action_block["elements"][0]["value"] == "U999"


def test_slot_list_includes_hint_context_block():
    text = "1 slot available:\n1. 10:00 AM IST"
    blocks = format_reply(text, user_id="U123")
    context_block = next((b for b in blocks if b["type"] == "context"), None)
    assert context_block is not None
    hint_text = context_block["elements"][0]["text"]
    assert "time" in hint_text or "chat" in hint_text


def test_booking_confirmation_returns_confirm_and_cancel_buttons():
    text = "Book 10:00 AM IST on Friday with ananya@nst.edu for 60 min. Confirm? (yes/no)"
    blocks = format_reply(text, user_id="U123")
    action_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [e["action_id"] for e in action_block["elements"]]
    assert "confirm_booking" in action_ids
    assert "cancel_booking" in action_ids


def test_booking_confirmation_embeds_user_id():
    text = "Book 10:00 AM IST. Confirm? (yes/no)"
    blocks = format_reply(text, user_id="U456")
    action_block = next(b for b in blocks if b["type"] == "actions")
    confirm_btn = next(e for e in action_block["elements"] if e["action_id"] == "confirm_booking")
    assert confirm_btn["value"] == "U456"


def test_pr_summary_returns_merge_and_comment_buttons():
    text = "PR #42: Add login flow\nStatus: 2 approvals, CI passing"
    blocks = format_reply(text, user_id="U123")
    action_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [e["action_id"] for e in action_block["elements"]]
    assert "merge_pr" in action_ids
    assert "comment_pr" in action_ids


def test_pr_summary_embeds_user_id():
    text = "PR #7: Fix typo"
    blocks = format_reply(text, user_id="U789")
    action_block = next(b for b in blocks if b["type"] == "actions")
    merge_btn = next(e for e in action_block["elements"] if e["action_id"] == "merge_pr")
    assert merge_btn["value"] == "U789"


def test_plain_text_returns_single_section_block():
    text = "Welcome to bookMyCal! Please send your Anthropic API key."
    blocks = format_reply(text)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "section"
    assert blocks[0]["text"]["text"] == text


def test_empty_text_returns_fallback_block():
    blocks = format_reply("")
    assert len(blocks) == 1
    assert blocks[0]["type"] == "section"


def test_format_reply_user_id_none_does_not_crash():
    """When user_id is not provided, button values default to empty string."""
    text = "Book 10:00 AM IST. Confirm? (yes/no)"
    blocks = format_reply(text)  # no user_id
    action_block = next(b for b in blocks if b["type"] == "actions")
    confirm_btn = next(e for e in action_block["elements"] if e["action_id"] == "confirm_booking")
    assert confirm_btn["value"] == ""


def test_plain_message_with_yes_no_not_misclassified_as_confirmation():
    """A message containing 'yes/no' but not 'Confirm?' stays as plain text."""
    text = "Do you want morning or afternoon? yes/no"
    blocks = format_reply(text)
    assert all(b["type"] == "section" for b in blocks)
    assert not any(b["type"] == "actions" for b in blocks)
