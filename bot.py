import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from agent import run_agent_turn
from onboarding import handle_onboarding_step, trigger_github_setup, trigger_google_auth
from prompts import MSG_ONBOARDING_START, MSG_READY
from session import (
    BOOKED,
    IDLE,
    ONBOARDING_GITHUB_PAT,
    get_session,
    reset_booking_ctx,
    reset_github_ctx,
    reset_session,
    save_session,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_text = update.message.text
    session = get_session(chat_id)

    try:
        if session["state"].startswith("ONBOARDING"):
            reply = await handle_onboarding_step(session, user_text, chat_id)
        else:
            reply = await run_agent_turn(session, user_text, chat_id)

            if session["state"] == BOOKED:
                reset_booking_ctx(session)

        save_session(chat_id, session)
        await update.message.reply_text(reply)

    except Exception as exc:
        logger.exception("Error handling message from chat_id=%s: %s", chat_id, exc)
        try:
            await update.message.reply_text("Something went wrong. Please try again.")
        except Exception:
            pass


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = reset_session(chat_id)

    if session["state"] == IDLE:
        # Env vars fully configured — skip onboarding
        await update.message.reply_text(MSG_READY)
    else:
        await update.message.reply_text(MSG_ONBOARDING_START)


async def cmd_reauth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete saved Google token and re-run OAuth flow."""
    chat_id = update.effective_chat.id
    token_path = os.path.join(os.path.dirname(__file__), ".google_tokens", f"{chat_id}.json")
    if os.path.exists(token_path):
        os.remove(token_path)

    session = get_session(chat_id)
    session["ctx"]["google_authed"] = False
    save_session(chat_id, session)

    reply = await trigger_google_auth(chat_id, session)
    save_session(chat_id, session)
    await update.message.reply_text(reply)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if session["state"].startswith("ONBOARDING"):
        await update.message.reply_text("Onboarding is still in progress. Complete setup first.")
        return

    reset_booking_ctx(session)
    save_session(chat_id, session)
    await update.message.reply_text("Booking context cleared. " + MSG_READY)


async def cmd_github(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Connect or reconnect a GitHub Personal Access Token."""
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if session["ctx"].get("github_authed"):
        username = session["ctx"].get("github_username", "unknown")
        # If already in the middle of re-auth flow, don't double-trigger
        if session["state"] == ONBOARDING_GITHUB_PAT:
            await update.message.reply_text(
                f"Already waiting for your GitHub token. Paste it now, or type /start to cancel."
            )
            return
        # Second /github call = re-auth: clear existing auth and start fresh
        reset_github_ctx(session)
        save_session(chat_id, session)

    reply = await trigger_github_setup(chat_id, session)
    save_session(chat_id, session)
    await update.message.reply_text(reply)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    ctx = session["ctx"]

    lines = [
        f"State: {session['state']}",
        f"Org email: {ctx.get('org_email') or 'not set'}",
        f"Office hours: {ctx['office_hours']['start']} - {ctx['office_hours']['end']} IST",
        f"Working days: {', '.join(ctx.get('working_days') or [])}",
        f"Google authed: {ctx.get('google_authed', False)}",
        f"GitHub authed: {ctx.get('github_authed', False)}",
        f"GitHub user: {ctx.get('github_username') or 'not set'}",
        f"Attendee: {ctx.get('attendee_email') or 'none'}",
        f"Date: {ctx.get('date') or 'none'}",
        f"Duration: {ctx.get('duration_mins') or 'none'} mins",
        f"Messages in history: {len(session['messages'])}",
    ]
    await update.message.reply_text("\n".join(lines))


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment or .env file.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reauth", cmd_reauth))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("github", cmd_github))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started. Polling for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
