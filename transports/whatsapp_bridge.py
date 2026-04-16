import datetime
import json
import logging
from contextlib import AsyncExitStack
from collections import deque
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class WhatsAppBridge:
    """Wrap the WhatsApp MCP server as a stdio subprocess."""

    def __init__(self, command: str, args: list[str] | None = None) -> None:
        self._command = command
        self._args = args or []
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self.self_jid: str | None = None
        self._recent_sent: deque[tuple[str, str, float]] = deque(maxlen=50)

    async def connect(self) -> None:
        """Spawn the MCP server subprocess and initialize the session."""
        self._exit_stack = AsyncExitStack()
        server_params = StdioServerParameters(command=self._command, args=self._args)
        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        logger.info("WhatsApp MCP bridge connected")

    async def disconnect(self) -> None:
        """Shut down the MCP session and subprocess."""
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._session = None
            logger.info("WhatsApp MCP bridge disconnected")

    async def _call_tool(self, name: str, args: dict | None = None) -> list | dict:
        """Call an MCP tool and decode its JSON payload."""
        if self._session is None:
            raise RuntimeError("Bridge not connected. Call connect() first.")

        result = await self._session.call_tool(name, arguments=args or {})
        if result.structuredContent is not None:
            structured = result.structuredContent
            if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
                return structured["result"]
            return structured
        if not result.content:
            return []

        decoded_items: list[Any] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text is None:
                continue
            try:
                decoded_items.append(json.loads(text))
            except json.JSONDecodeError:
                decoded_items.append(text)

        if not decoded_items:
            return []
        if len(decoded_items) == 1:
            return decoded_items[0]
        return decoded_items

    async def poll_messages(self, after_timestamp: float) -> list[dict]:
        """Return new incoming direct messages since `after_timestamp`."""
        chats = await self._call_tool("list_chats", {"limit": 100})
        dm_jids = [
            chat["jid"]
            for chat in chats
            if not chat.get("is_group", False) and not chat["jid"].endswith("@g.us")
        ]

        after_iso = datetime.datetime.fromtimestamp(
            after_timestamp,
            tz=datetime.timezone.utc,
        ).isoformat()
        messages: list[dict] = []

        for jid in dm_jids:
            raw_messages = await self._call_tool(
                "list_messages",
                {"chat_jid": jid, "limit": 50, "after": after_iso, "include_context": False},
            )
            for msg in raw_messages:
                sender = msg.get("sender", "")
                text = (msg.get("text") or "").strip()
                if not text:
                    continue

                timestamp = msg.get("timestamp")
                if isinstance(timestamp, str):
                    timestamp = datetime.datetime.fromisoformat(timestamp).timestamp()
                ts = float(timestamp) if timestamp else after_timestamp

                # Self-chat messages from the owner are also marked is_from_me=1.
                # Keep those, but suppress the messages that this bot itself just sent.
                is_self_chat = sender and jid.startswith(sender)
                if msg.get("is_from_me") and not is_self_chat:
                    continue

                if any(
                    sent_jid == jid and sent_text == text and abs(sent_ts - ts) < 15
                    for sent_jid, sent_text, sent_ts in self._recent_sent
                ):
                    continue

                if self.self_jid and sender == self.self_jid:
                    continue

                messages.append(
                    {
                        "sender_jid": sender or jid,
                        "text": text,
                        "timestamp": ts,
                    }
                )

        return messages

    async def send_message(self, jid: str, text: str) -> None:
        """Send a text message to a WhatsApp JID or phone number."""
        # Preserve non-standard JIDs such as self-chat @lid and group @g.us.
        # Only strip the personal-chat server suffix where the bridge accepts
        # a bare phone number interchangeably.
        recipient = jid
        if jid.endswith("@s.whatsapp.net"):
            recipient = jid.split("@")[0]
        await self._call_tool("send_message", {"recipient": recipient, "message": text})
        self._recent_sent.append((jid, text.strip(), datetime.datetime.now(datetime.timezone.utc).timestamp()))
