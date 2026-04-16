# whatsapp.py
import asyncio
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from core.agent import run_agent_turn
from core.onboarding import handle_onboarding_step, start_for_new_user, trigger_github_setup
from core.session import BOOKED, _sessions, get_session, reset_booking_ctx, save_session
from transports.whatsapp_bridge import WhatsAppBridge

load_dotenv()
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("anthropic").setLevel(logging.WARNING)
logging.getLogger("anthropic._base_client").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

POLL_INTERVAL = 2  # seconds between poll cycles
BRIDGE_RESTART_DELAY = 5  # seconds before retry after crash
_GITHUB_TRIGGER_PHRASES = {
    "connect github",
    "setup github",
    "link github",
    "add github",
    "/github",
}


def _resolve_mcp_launch(server_dir: Path) -> tuple[str, list[str]]:
    """Resolve the stdio command that should launch the MCP server.

    Guard against the common misconfiguration where WHATSAPP_MCP_BINARY is set
    to the Go bridge binary (`whatsapp-client`), which is not an MCP server.
    """
    configured_binary = os.getenv("WHATSAPP_MCP_BINARY")
    if configured_binary:
        configured_path = Path(configured_binary).expanduser()
        if configured_path.name == "uv":
            return "uv", ["--directory", str(server_dir), "run", "main.py"]
        if configured_path.name == "whatsapp-client":
            logger.warning(
                "Ignoring WHATSAPP_MCP_BINARY=%s because it points to the Go bridge, "
                "not the MCP server. Falling back to the Python MCP server entrypoint.",
                configured_binary,
            )
        else:
            return str(configured_path), [str(server_dir / "main.py")]

    if shutil.which("uv"):
        return "uv", ["--directory", str(server_dir), "run", "main.py"]

    return sys.executable, [str(server_dir / "main.py")]


def _github_setup_requested(text: str, session: dict) -> bool:
    """Return True when the user wants to connect GitHub and hasn't done so yet.

    Does not trigger during onboarding (the bot is already guiding the user
    through a different flow) or when GitHub is already connected.
    """
    if session["ctx"].get("github_authed"):
        return False
    if session["state"].startswith("ONBOARDING"):
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in _GITHUB_TRIGGER_PHRASES)


async def handle_whatsapp_message(
    bridge: WhatsAppBridge,
    jid: str,
    text: str,
    seen_jids: set,
) -> None:
    """Process a single incoming message and send the reply."""
    session = get_session(jid)

    if jid not in seen_jids:
        welcome = start_for_new_user(jid, session)
        seen_jids.add(jid)
        await bridge.send_message(jid, welcome)
        if session["state"].startswith("ONBOARDING"):
            save_session(jid, session)
            return  # wait for onboarding answer before processing this message

    reply = "Something went wrong. Please try again."  # default fallback
    try:
        if session["state"].startswith("ONBOARDING"):
            reply = await handle_onboarding_step(session, text, jid)
        elif _github_setup_requested(text, session):
            reply = await trigger_github_setup(jid, session)
        else:
            reply = await run_agent_turn(session, text, jid)
            if session["state"] == BOOKED:
                reset_booking_ctx(session)
    except Exception:
        logger.exception("Unhandled error for JID %s", jid)

    save_session(jid, session)
    try:
        await bridge.send_message(jid, reply)
    except Exception:
        logger.exception("Failed to send reply to %s", jid)


async def run_poll_loop(bridge: WhatsAppBridge) -> None:
    """Main 2-second poll loop. Runs indefinitely."""
    seen_jids: set = set(_sessions.keys())  # seed from in-memory sessions to avoid re-welcoming on restart
    last_poll = time.time() - POLL_INTERVAL

    while True:
        await asyncio.sleep(POLL_INTERVAL)
        now = time.time()
        try:
            messages = await bridge.poll_messages(after_timestamp=last_poll)
        except Exception:
            logger.exception("poll_messages failed")
            last_poll = now
            continue

        last_poll = now
        for msg in messages:
            await handle_whatsapp_message(
                bridge,
                jid=msg["sender_jid"],
                text=msg["text"],
                seen_jids=seen_jids,
            )


async def main() -> None:
    default_server_dir = (
        Path(__file__).resolve().parent.parent / "whatsapp-mcp" / "whatsapp-mcp-server"
    )
    server_dir = Path(os.getenv("WHATSAPP_MCP_SERVER_DIR", str(default_server_dir))).expanduser()
    if not server_dir.exists():
        raise SystemExit(
            f"WhatsApp MCP server directory not found: {server_dir}\n"
            "Set WHATSAPP_MCP_SERVER_DIR to the whatsapp-mcp-server folder."
        )

    command, args = _resolve_mcp_launch(server_dir)

    bridge = WhatsAppBridge(command, args)

    try:
        await bridge.connect()
    except Exception as exc:
        raise SystemExit(f"Failed to connect to WhatsApp bridge: {exc}") from exc

    logger.info("WhatsApp bot started. Scanning for messages every %ds.", POLL_INTERVAL)

    try:
        await run_poll_loop(bridge)
    except Exception:
        logger.exception("Poll loop crashed — attempting restart in %ds", BRIDGE_RESTART_DELAY)
        try:
            await bridge.disconnect()
        except Exception:
            logger.exception("Bridge disconnect failed during crash recovery")
        await asyncio.sleep(BRIDGE_RESTART_DELAY)
        try:
            bridge = WhatsAppBridge(command, args)
            await bridge.connect()
            await run_poll_loop(bridge)
        except Exception as exc:
            raise SystemExit(f"Bridge restart failed: {exc}") from exc
    finally:
        await bridge.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
