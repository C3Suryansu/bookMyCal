# tests/test_whatsapp_bridge.py
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from transports.whatsapp_bridge import WhatsAppBridge


@pytest.fixture
def bridge():
    b = WhatsAppBridge("/fake/binary")
    b.self_jid = "bot123@s.whatsapp.net"
    return b


@pytest.mark.asyncio
async def test_poll_messages_filters_groups(bridge):
    """Group chats (JIDs ending @g.us) are excluded."""
    chats_response = [
        {"jid": "group1@g.us", "is_group": True},
        {"jid": "+911234567890@s.whatsapp.net", "is_group": False},
    ]
    messages_for_dm = [
        {"sender": "+911234567890@s.whatsapp.net", "text": "hello", "timestamp": 1700000010.0, "is_from_me": False},
    ]

    async def fake_call_tool(name, args=None):
        if name == "list_chats":
            return chats_response
        if name == "list_messages":
            return messages_for_dm
        return []

    bridge._call_tool = fake_call_tool
    results = await bridge.poll_messages(after_timestamp=1700000000.0)
    assert len(results) == 1
    assert results[0]["sender_jid"] == "+911234567890@s.whatsapp.net"


@pytest.mark.asyncio
async def test_poll_messages_filters_self_messages(bridge):
    """Messages from the bot's own JID are excluded."""
    chats_response = [{"jid": "+911234567890@s.whatsapp.net", "is_group": False}]
    messages = [
        {"sender": "bot123@s.whatsapp.net", "text": "I said this", "timestamp": 1700000010.0, "is_from_me": True},
        {"sender": "+911234567890@s.whatsapp.net", "text": "user said this", "timestamp": 1700000020.0, "is_from_me": False},
    ]

    async def fake_call_tool(name, args=None):
        if name == "list_chats":
            return chats_response
        return messages

    bridge._call_tool = fake_call_tool
    results = await bridge.poll_messages(after_timestamp=1700000000.0)
    assert len(results) == 1
    assert results[0]["text"] == "user said this"


@pytest.mark.asyncio
async def test_poll_messages_skips_non_text(bridge):
    """Messages without a text field (media) are excluded."""
    chats_response = [{"jid": "+911234567890@s.whatsapp.net", "is_group": False}]
    messages = [
        {"sender": "+911234567890@s.whatsapp.net", "text": None, "timestamp": 1700000010.0, "is_from_me": False},
        {"sender": "+911234567890@s.whatsapp.net", "text": "hi", "timestamp": 1700000020.0, "is_from_me": False},
    ]

    async def fake_call_tool(name, args=None):
        if name == "list_chats":
            return chats_response
        return messages

    bridge._call_tool = fake_call_tool
    results = await bridge.poll_messages(after_timestamp=1700000000.0)
    assert len(results) == 1
    assert results[0]["text"] == "hi"


@pytest.mark.asyncio
async def test_send_message_calls_tool(bridge):
    """send_message calls the MCP send_message tool with the correct JID."""
    calls = []

    async def fake_call_tool(name, args=None):
        calls.append((name, args))

    bridge._call_tool = fake_call_tool
    await bridge.send_message("+911234567890@s.whatsapp.net", "hello")
    assert len(calls) == 1
    assert calls[0][0] == "send_message"
    assert calls[0][1]["recipient"] == "+911234567890"
    assert calls[0][1]["message"] == "hello"


@pytest.mark.asyncio
async def test_send_message_preserves_lid_jid(bridge):
    """Self-chat @lid JIDs must be sent intact, not coerced to phone chats."""
    calls = []

    async def fake_call_tool(name, args=None):
        calls.append((name, args))

    bridge._call_tool = fake_call_tool
    await bridge.send_message("261391894233257@lid", "hello")
    assert len(calls) == 1
    assert calls[0][0] == "send_message"
    assert calls[0][1]["recipient"] == "261391894233257@lid"
    assert calls[0][1]["message"] == "hello"
