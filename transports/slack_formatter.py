import logging
import re

logger = logging.getLogger(__name__)


def format_reply(text: str, user_id: str | None = None) -> list[dict]:
    """Convert agent reply text to Slack Block Kit blocks.

    Detects the reply type by pattern matching and returns the appropriate
    Block Kit structure. Falls back to a plain text section block.

    user_id is embedded in button values so the bot can verify ownership
    when a user clicks an interactive button.
    """
    if not text:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": "_No response._"}}]

    if _is_slot_list(text):
        return _build_slot_blocks(text, user_id)
    if _is_booking_confirmation(text):
        return _build_confirm_blocks(text, user_id)
    if _is_pr_summary(text):
        return _build_pr_blocks(text, user_id)

    return _build_text_block(text)


def _is_slot_list(text: str) -> bool:
    return bool(re.search(r"slots?\s+available", text, re.IGNORECASE))


def _is_booking_confirmation(text: str) -> bool:
    return bool(re.search(r"Confirm\?", text))


def _is_pr_summary(text: str) -> bool:
    return bool(re.search(r"PR #\d+", text))


def _extract_slots(text: str) -> list[str]:
    """Return slot strings from a numbered list, e.g. '1. 10:00 AM IST'."""
    return re.findall(r"^\s*\d+\.\s+(.+)$", text, re.MULTILINE)


def _build_slot_blocks(text: str, user_id: str | None) -> list[dict]:
    """Return slot list blocks with one button per slot."""
    slots = _extract_slots(text)
    header = text.split("\n")[0]

    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": slot.strip()[:75]},
            "action_id": f"select_slot_{i + 1}",
            "value": user_id or "",
        }
        for i, slot in enumerate(slots[:25])  # Slack actions block max 25 elements
    ]

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
    ]
    if buttons:
        blocks.append({"type": "actions", "elements": buttons})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "Or type a time in the chat."}],
    })
    return blocks


def _build_confirm_blocks(text: str, user_id: str | None) -> list[dict]:
    """Return booking confirmation block with Confirm/Cancel buttons."""
    body = re.sub(r"\s*\(yes/no\)\s*", "", text).strip()

    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Confirm"},
                    "action_id": "confirm_booking",
                    "style": "primary",
                    "value": user_id or "",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Cancel"},
                    "action_id": "cancel_booking",
                    "style": "danger",
                    "value": user_id or "",
                },
            ],
        },
    ]


def _build_pr_blocks(text: str, user_id: str | None) -> list[dict]:
    """Return PR summary block with Merge/Comment buttons."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔀 Merge"},
                    "action_id": "merge_pr",
                    "style": "primary",
                    "value": user_id or "",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "💬 Comment"},
                    "action_id": "comment_pr",
                    "value": user_id or "",
                },
            ],
        },
    ]


def _build_text_block(text: str) -> list[dict]:
    """Return a plain text section block."""
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
