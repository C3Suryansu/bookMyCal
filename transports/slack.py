# slack_bot.py
import asyncio
import logging
import os
import re

from dotenv import load_dotenv
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from core.agent import run_agent_turn
from core.onboarding import handle_onboarding_step, start_for_new_user, trigger_github_setup
from core.session import BOOKED, get_session, reset_booking_ctx, save_session
from transports.slack_formatter import format_reply

load_dotenv()
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("anthropic").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_GITHUB_TRIGGER_PHRASES = {
    "/github",
    "connect github",
    "setup github",
    "link github",
    "add github",
}

app = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN", "xoxb-placeholder"))

_bot_user_id: str | None = None


async def _get_bot_user_id(client) -> str:
    """Return the bot's Slack user ID, fetching from the API on first call only."""
    global _bot_user_id
    if _bot_user_id is None:
        info = await client.auth_test()
        _bot_user_id = info["user_id"]
    return _bot_user_id


# ---------------------------------------------------------------------------
# Pure helpers (tested in tests/test_slack_bot.py)
# ---------------------------------------------------------------------------

def _is_onboarded(user_id: str) -> bool:
    """Return True if the user has completed onboarding (session state is not ONBOARDING_*)."""
    session = get_session(user_id)
    return not session["state"].startswith("ONBOARDING")


def _extract_mention_text(text: str, bot_user_id: str) -> str:
    """Strip the bot mention (<@BOT_USER_ID>) from message text and return clean input."""
    return re.sub(rf"<@{re.escape(bot_user_id)}>", "", text).strip()


def _check_button_ownership(action_user_id: str, initiator_user_id: str) -> bool:
    """Return True if the user who clicked a button is the one who initiated the flow."""
    return action_user_id == initiator_user_id


# ---------------------------------------------------------------------------
# Event: @bookMyCal mention in a channel
# ---------------------------------------------------------------------------

@app.event("app_mention")
async def handle_mention(event, say, client):
    user_id = event["user"]
    thread_ts = event.get("thread_ts") or event["ts"]
    channel = event["channel"]

    bot_user_id = await _get_bot_user_id(client)
    text = _extract_mention_text(event.get("text", ""), bot_user_id)

    session = get_session(user_id)

    if not _is_onboarded(user_id):
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            text="Hey! You need to set up your account first. I've sent you a DM.",
        )
        dm = await client.conversations_open(users=user_id)
        dm_channel = dm["channel"]["id"]
        welcome = start_for_new_user(user_id, session)
        save_session(user_id, session)
        await client.chat_postMessage(channel=dm_channel, text=welcome)
        return

    try:
        reply = await run_agent_turn(session, text, user_id)
        if session["state"] == BOOKED:
            reset_booking_ctx(session)
    except Exception:
        logger.exception("Agent error for user %s", user_id)
        reply = "Something went wrong. Please try again."

    save_session(user_id, session)
    blocks = format_reply(reply, user_id=user_id)
    await say(blocks=blocks, text=reply, thread_ts=thread_ts)


# ---------------------------------------------------------------------------
# Event: DM message
# ---------------------------------------------------------------------------

@app.event("message")
async def handle_dm(event, say, client):
    # Only handle DMs; ignore messages from bots (including self)
    if event.get("channel_type") != "im":
        return
    if event.get("bot_id") or event.get("subtype"):
        return

    user_id = event["user"]
    text = event.get("text", "").strip()
    if not text:
        return

    session = get_session(user_id)

    try:
        if session["state"].startswith("ONBOARDING"):
            reply = await handle_onboarding_step(session, text, user_id)
        elif (
            text.lower() in _GITHUB_TRIGGER_PHRASES
            and not session["ctx"].get("github_authed")
        ):
            reply = await trigger_github_setup(user_id, session)
        else:
            reply = await run_agent_turn(session, text, user_id)
            if session["state"] == BOOKED:
                reset_booking_ctx(session)
    except Exception:
        logger.exception("DM error for user %s", user_id)
        reply = "Something went wrong. Please try again."

    save_session(user_id, session)
    blocks = format_reply(reply, user_id=user_id)
    await say(blocks=blocks, text=reply)


# ---------------------------------------------------------------------------
# Button actions
# ---------------------------------------------------------------------------

@app.action(re.compile(r"select_slot_\d+"))
async def handle_slot_selection(ack, body, client):
    await ack()
    action = body["actions"][0]
    action_user_id = body["user"]["id"]
    initiator_user_id = action["value"]

    if not _check_button_ownership(action_user_id, initiator_user_id):
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="This isn't your booking.",
        )
        return

    slot_number = action["action_id"].split("_")[-1]
    session = get_session(action_user_id)

    try:
        reply = await run_agent_turn(session, slot_number, action_user_id)
    except Exception:
        logger.exception("Slot selection error for user %s", action_user_id)
        reply = "Something went wrong. Please try again."

    save_session(action_user_id, session)
    msg = body["message"]
    thread_ts = msg.get("thread_ts") or msg["ts"]
    blocks = format_reply(reply, user_id=action_user_id)
    await client.chat_postMessage(
        channel=body["channel"]["id"],
        thread_ts=thread_ts,
        blocks=blocks,
        text=reply,
    )


@app.action("confirm_booking")
async def handle_confirm_booking(ack, body, client):
    await ack()
    action = body["actions"][0]
    action_user_id = body["user"]["id"]
    initiator_user_id = action["value"]

    if not _check_button_ownership(action_user_id, initiator_user_id):
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="This isn't your booking.",
        )
        return

    session = get_session(action_user_id)

    try:
        reply = await run_agent_turn(session, "yes", action_user_id)
        if session["state"] == BOOKED:
            reset_booking_ctx(session)
    except Exception:
        logger.exception("Confirm booking error for user %s", action_user_id)
        reply = "Something went wrong. Please try again."

    save_session(action_user_id, session)
    blocks = format_reply(reply, user_id=action_user_id)
    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        blocks=blocks,
        text=reply,
    )


@app.action("cancel_booking")
async def handle_cancel_booking(ack, body, client):
    await ack()
    action = body["actions"][0]
    action_user_id = body["user"]["id"]
    initiator_user_id = action["value"]

    if not _check_button_ownership(action_user_id, initiator_user_id):
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="This isn't your booking.",
        )
        return

    session = get_session(action_user_id)

    try:
        reply = await run_agent_turn(session, "no", action_user_id)
    except Exception:
        logger.exception("Cancel booking error for user %s", action_user_id)
        reply = "Something went wrong. Please try again."

    save_session(action_user_id, session)
    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        blocks=format_reply(reply, user_id=action_user_id),
        text=reply,
    )


@app.action("merge_pr")
async def handle_merge_pr(ack, body, client):
    await ack()
    action = body["actions"][0]
    action_user_id = body["user"]["id"]
    initiator_user_id = action["value"]

    if not _check_button_ownership(action_user_id, initiator_user_id):
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="This isn't your PR action.",
        )
        return

    session = get_session(action_user_id)

    try:
        reply = await run_agent_turn(session, "merge", action_user_id)
    except Exception:
        logger.exception("Merge PR error for user %s", action_user_id)
        reply = "Something went wrong. Please try again."

    save_session(action_user_id, session)
    blocks = format_reply(reply, user_id=action_user_id)
    await client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        blocks=blocks,
        text=reply,
    )


@app.action("comment_pr")
async def handle_comment_pr(ack, body, client):
    await ack()
    action_user_id = body["user"]["id"]
    initiator_user_id = body["actions"][0]["value"]

    if not _check_button_ownership(action_user_id, initiator_user_id):
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="This isn't your PR action.",
        )
        return

    try:
        await client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "comment_pr_submit",
                "private_metadata": body["channel"]["id"],
                "title": {"type": "plain_text", "text": "Add Comment"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "comment_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "comment_input",
                            "multiline": True,
                            "placeholder": {"type": "plain_text", "text": "Your comment..."},
                        },
                        "label": {"type": "plain_text", "text": "Comment"},
                    }
                ],
            },
        )
    except Exception:
        logger.exception("Comment modal error for user %s", action_user_id)
        await client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=action_user_id,
            text="Something went wrong. Please try again.",
        )


@app.view("comment_pr_submit")
async def handle_comment_submit(ack, body, client, view):
    await ack()
    user_id = body["user"]["id"]
    comment_text = view["state"]["values"]["comment_block"]["comment_input"]["value"]
    channel = view["private_metadata"]

    session = get_session(user_id)

    try:
        reply = await run_agent_turn(session, f"comment: {comment_text}", user_id)
    except Exception:
        logger.exception("Comment submit error for user %s", user_id)
        reply = "Something went wrong. Please try again."

    save_session(user_id, session)
    blocks = format_reply(reply, user_id=user_id)
    await client.chat_postMessage(channel=channel, blocks=blocks, text=reply)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    bot_token = os.getenv("SLACK_BOT_TOKEN")
    app_token = os.getenv("SLACK_APP_TOKEN")

    if not bot_token:
        raise SystemExit(
            "SLACK_BOT_TOKEN is not set.\n"
            "Create a Slack app at https://api.slack.com/apps and set the token in .env"
        )
    if not app_token:
        raise SystemExit(
            "SLACK_APP_TOKEN is not set.\n"
            "Enable Socket Mode in your Slack app and set the app-level token in .env"
        )

    handler = AsyncSocketModeHandler(app, app_token)
    logger.info("bookMyCal Slack bot starting (Socket Mode)...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
