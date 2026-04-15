import json
import logging
from datetime import datetime, timezone
import re

import anthropic
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import ANTHROPIC_MODEL
from github_tools import GITHUB_TOOLS, dispatch_github_tool
from onboarding import load_credentials
from prompts import SYSTEM_PROMPT
from session import (
    AWAITING_CHOICE,
    AWAITING_CONFIRM,
    BOOKED,
    FALLBACK_DECIDE,
    append_message,
    save_session,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (sent to Claude so it knows what to call)
# ---------------------------------------------------------------------------

CALENDAR_TOOLS = [
    {
        "name": "lookup_person",
        "description": (
            "Look up a person's email address by their name in the org directory and personal contacts. "
            "Use this whenever the user gives a first name, last name, or partial name instead of an email. "
            "Returns a list of matches with name and email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The person's name or partial name to search for",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "calendar_events_list",
        "description": (
            "List events on any calendar with attendance/response status. "
            "Use 'primary' for the authenticated user's own calendar. "
            "For attendees on the same org, pass their email as calendar_id — if they have shared "
            "their calendar you will get full event details including their responseStatus. "
            "If permission is denied, the result will contain a 'permission_denied' flag — "
            "fall back to calendar_freebusy in that case. "
            "Always treat events with responseStatus='declined' as FREE time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID: 'primary' for own calendar, or attendee email for org calendars.",
                },
                "time_min": {
                    "type": "string",
                    "description": "Start of range, UTC ISO string e.g. 2024-04-07T09:00:00Z",
                },
                "time_max": {
                    "type": "string",
                    "description": "End of range, UTC ISO string e.g. 2024-04-07T18:00:00Z",
                },
            },
            "required": ["calendar_id", "time_min", "time_max"],
        },
    },
    {
        "name": "calendar_freebusy",
        "description": (
            "Check free/busy availability for one or more email addresses over a time range. "
            "Returns busy blocks as UTC ISO strings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "emails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of email addresses to check",
                },
                "time_min": {
                    "type": "string",
                    "description": "Start of range, UTC ISO string e.g. 2024-04-05T09:00:00Z",
                },
                "time_max": {
                    "type": "string",
                    "description": "End of range, UTC ISO string e.g. 2024-04-05T18:00:00Z",
                },
            },
            "required": ["emails", "time_min", "time_max"],
        },
    },
    {
        "name": "calendar_events_create",
        "description": "Create a calendar event on the user's calendar and invite attendees.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title"},
                "start": {
                    "type": "string",
                    "description": "Start datetime, UTC ISO string e.g. 2024-04-05T10:00:00Z",
                },
                "end": {
                    "type": "string",
                    "description": "End datetime, UTC ISO string e.g. 2024-04-05T11:00:00Z",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses",
                },
                "description": {
                    "type": "string",
                    "description": "Optional event description",
                },
                "add_meet_link": {
                    "type": "boolean",
                    "description": "If true, attach a Google Meet video call link to the event. Default true.",
                },
            },
            "required": ["summary", "start", "end", "attendees"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution against Google Calendar API
# ---------------------------------------------------------------------------

def _get_calendar_service(chat_id: int):
    creds = load_credentials(chat_id)
    if not creds:
        raise RuntimeError("Google credentials not found. Please type /start to re-authorise.")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _execute_lookup_person(chat_id: int, name: str) -> dict:
    creds = load_credentials(chat_id)
    if not creds:
        return {"error": "Not authenticated"}

    seen_emails = set()
    matches = []

    def _add(display, email, source):
        email = email.lower().strip()
        if email and email not in seen_emails:
            seen_emails.add(email)
            matches.append({"name": display, "email": email, "source": source})

    try:
        people_svc = build("people", "v1", credentials=creds, cache_discovery=False)

        # 1. Org directory (Google Workspace)
        try:
            result = people_svc.people().searchDirectoryPeople(
                query=name,
                readMask="names,emailAddresses",
                sources=["DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"],
                pageSize=10,
            ).execute()
            for person in result.get("people", []):
                display = (person.get("names") or [{}])[0].get("displayName", "")
                for e in person.get("emailAddresses", []):
                    _add(display, e.get("value", ""), "directory")
            logger.info("Directory search '%s': %d results", name, len(result.get("people", [])))
        except HttpError as exc:
            logger.warning("Directory search failed (%s): %s", exc.resp.status, exc)

        # 2. Saved contacts
        try:
            result = people_svc.people().searchContacts(
                query=name,
                readMask="names,emailAddresses",
                pageSize=10,
            ).execute()
            for item in result.get("results", []):
                p = item.get("person", {})
                display = (p.get("names") or [{}])[0].get("displayName", "")
                for e in p.get("emailAddresses", []):
                    _add(display, e.get("value", ""), "contacts")
            logger.info("Contacts search '%s': %d results", name, len(result.get("results", [])))
        except HttpError as exc:
            logger.warning("Contacts search failed (%s): %s", exc.resp.status, exc)

        # 3. Other contacts (auto-saved from Gmail/Calendar interactions)
        try:
            result = people_svc.otherContacts().search(
                query=name,
                readMask="names,emailAddresses",
                pageSize=10,
            ).execute()
            for item in result.get("results", []):
                p = item.get("person", {})
                display = (p.get("names") or [{}])[0].get("displayName", "")
                for e in p.get("emailAddresses", []):
                    _add(display, e.get("value", ""), "other_contacts")
            logger.info("Other contacts search '%s': %d results", name, len(result.get("results", [])))
        except HttpError as exc:
            logger.warning("Other contacts search failed (%s): %s", exc.resp.status, exc)

    except Exception as exc:
        logger.exception("lookup_person unexpected error: %s", exc)
        return {"error": str(exc), "matches": []}

    logger.info("lookup_person '%s' total matches: %d", name, len(matches))
    return {"matches": matches}


def _execute_events_list(chat_id: int, calendar_id: str, time_min: str, time_max: str) -> dict:
    service = _get_calendar_service(chat_id)
    try:
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except HttpError as exc:
        if exc.resp.status in (403, 404):
            return {"permission_denied": True, "calendar_id": calendar_id}
        raise
    events = []
    for event in result.get("items", []):
        # Determine response status for the calendar owner
        # For 'primary' (own calendar): look for self=True attendee entry
        # For an attendee's calendar: look for their email in the attendees list
        user_response = "accepted"  # default: organizer with no attendee list
        attendees = event.get("attendees", [])
        # Try self flag first (works for own calendar)
        for att in attendees:
            if att.get("self"):
                user_response = att.get("responseStatus", "accepted")
                break
        else:
            # For another person's calendar, find their entry by calendar_id email
            if calendar_id != "primary":
                for att in attendees:
                    if att.get("email", "").lower() == calendar_id.lower():
                        user_response = att.get("responseStatus", "accepted")
                        break
        events.append({
            "summary": event.get("summary", "(no title)"),
            "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date"),
            "end": event.get("end", {}).get("dateTime") or event.get("end", {}).get("date"),
            "responseStatus": user_response,
        })
    return {"events": events, "calendar_id": calendar_id}


def _execute_freebusy(chat_id: int, emails: list, time_min: str, time_max: str) -> dict:
    service = _get_calendar_service(chat_id)
    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": email} for email in emails],
    }
    result = service.freebusy().query(body=body).execute()
    # Return a simplified structure
    calendars = result.get("calendars", {})
    output = {}
    for email in emails:
        cal = calendars.get(email, {})
        errors = cal.get("errors", [])
        busy = cal.get("busy", [])
        output[email] = {"busy": busy, "errors": errors}
    return output


def _execute_create_event(
    chat_id: int,
    summary: str,
    start: str,
    end: str,
    attendees: list,
    description: str = "",
    add_meet_link: bool = True,
) -> dict:
    import uuid
    service = _get_calendar_service(chat_id)
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "attendees": [{"email": e} for e in attendees],
        "reminders": {"useDefault": True},
    }
    if add_meet_link:
        event["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    created = service.events().insert(
        calendarId="primary",
        body=event,
        sendUpdates="all",
        conferenceDataVersion=1 if add_meet_link else 0,
    ).execute()
    meet_link = None
    conference = created.get("conferenceData", {})
    for ep in conference.get("entryPoints", []):
        if ep.get("entryPointType") == "video":
            meet_link = ep.get("uri")
            break
    return {
        "id": created.get("id"),
        "summary": created.get("summary"),
        "start": created.get("start"),
        "end": created.get("end"),
        "htmlLink": created.get("htmlLink"),
        "meetLink": meet_link,
        "status": created.get("status"),
    }


async def _dispatch_tool(chat_id: int, tool_name: str, tool_input: dict) -> str:
    """Execute a tool call and return the result as a JSON string."""
    # Route GitHub tools to their own dispatcher
    if tool_name.startswith("github_"):
        return await dispatch_github_tool(chat_id, tool_name, tool_input)

    try:
        if tool_name == "lookup_person":
            result = _execute_lookup_person(chat_id, tool_input["name"])
        elif tool_name == "calendar_events_list":
            result = _execute_events_list(
                chat_id,
                tool_input["calendar_id"],
                tool_input["time_min"],
                tool_input["time_max"],
            )
        elif tool_name == "calendar_freebusy":
            result = _execute_freebusy(
                chat_id,
                tool_input["emails"],
                tool_input["time_min"],
                tool_input["time_max"],
            )
        elif tool_name == "calendar_events_create":
            result = _execute_create_event(
                chat_id,
                tool_input["summary"],
                tool_input["start"],
                tool_input["end"],
                tool_input["attendees"],
                tool_input.get("description", ""),
                tool_input.get("add_meet_link", True),
            )
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
        logger.info("Tool %s result: %s", tool_name, result)
        return json.dumps(result)
    except HttpError as exc:
        logger.error("Google API error in %s: %s", tool_name, exc)
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("Tool execution error in %s: %s", tool_name, exc)
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(api_key: str) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key=api_key,
        max_retries=1,
        timeout=12.0,
    )


def _normalize_content_blocks(content) -> list:
    normalized = []
    for block in content or []:
        if hasattr(block, "model_dump"):
            normalized.append(block.model_dump(mode="json", exclude_none=True))
        elif isinstance(block, dict):
            normalized.append(block)
        else:
            normalized.append(block)
    return normalized


def extract_text_reply(response) -> str:
    for block in response.content:
        if hasattr(block, "type") and block.type == "text":
            return block.text
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    return ""


def _infer_state_from_reply(reply: str) -> str | None:
    lower = reply.lower()
    if "event created" in lower or "booked" in lower or "done." in lower:
        return BOOKED
    if "confirm?" in lower or "shall i book?" in lower:
        return AWAITING_CONFIRM
    if "no available slots" in lower and (
        "instead" in lower or "try" in lower or "check" in lower
    ):
        return FALLBACK_DECIDE
    if (
        ("1." in reply or "1)" in reply)
        and ("ist" in lower or "am" in lower or "pm" in lower)
        and "?" in reply
    ):
        return AWAITING_CHOICE
    return None


def _format_ist(dt_str: str | None) -> str:
    if not dt_str:
        return "unknown time"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        ist = dt.astimezone(__import__("pytz").timezone("Asia/Kolkata"))
        return ist.strftime("%-I:%M %p IST")
    except Exception:
        return dt_str


def _tool_fallback_reply(tool_name: str, result_json: str) -> str | None:
    try:
        result = json.loads(result_json)
    except Exception:
        return None

    if tool_name == "calendar_events_list":
        events = result.get("events", [])
        if not events:
            return "Your calendar looks free for that time range."
        lines = ["Here’s your calendar for that period:"]
        for idx, event in enumerate(events[:6], start=1):
            lines.append(
                f"{idx}. {event.get('summary', '(no title)')} — "
                f"{_format_ist(event.get('start'))} to {_format_ist(event.get('end'))}"
            )
        if len(events) > 6:
            lines.append(f"And {len(events) - 6} more events.")
        return "\n".join(lines)

    if tool_name == "lookup_person":
        if result.get("error"):
            return "I couldn’t look that person up right now."
        matches = result.get("matches", [])
        if not matches:
            return "I couldn’t find anyone matching that name."
        if len(matches) == 1:
            match = matches[0]
            return f"Found {match.get('name', 'that person')} — {match.get('email', 'unknown email')}."
        lines = ["Found a few matches:"]
        for idx, match in enumerate(matches[:5], start=1):
            lines.append(f"{idx}. {match.get('name', 'Unknown')} — {match.get('email', 'unknown')}")
        return "\n".join(lines)

    if tool_name == "calendar_events_create":
        return (
            f"Booked. Event created: {result.get('summary', '(no title)')}. "
            f"{'Meet link: ' + result['meetLink'] if result.get('meetLink') else ''}".strip()
        )

    return None


async def _synthesize_tool_reply(
    client: anthropic.AsyncAnthropic,
    system_prompt: str,
    user_message: str,
    tool_results: list[dict],
) -> str:
    synthesis_lines = [
        f"Original user request: {user_message}",
        "Tool results:",
    ]
    for item in tool_results:
        synthesis_lines.append(json.dumps(item, ensure_ascii=False))
    synthesis_lines.append(
        "Using only these tool results, answer the user directly in plain concise text."
    )
    response = await client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": "\n".join(synthesis_lines)}],
    )
    return extract_text_reply(response)


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

async def run_agent_turn(session: dict, user_message: str, chat_id: int | str) -> str:
    api_key = session["ctx"].get("anthropic_api_key")
    if not api_key:
        return "No API key found. Please type /start to set up your account."

    client = _make_client(api_key)
    append_message(session, "user", user_message)

    ctx = session["ctx"]
    now_ist = datetime.now(timezone.utc).astimezone(
        __import__("pytz").timezone("Asia/Kolkata")
    )

    # Build GitHub context lines
    github_lines = []
    github_authed = ctx.get("github_authed", False)
    github_lines.append(f"GitHub authed: {github_authed}")
    if github_authed:
        github_username = ctx.get("github_username")
        if github_username:
            github_lines.append(f"GitHub username: {github_username}")
        default_repos = ctx.get("github_default_repos", [])
        if default_repos:
            repos_preview = ", ".join(default_repos[:5])
            github_lines.append(f"Cached repos (first 5): {repos_preview}")

    context_note = (
        f"\n\nCURRENT USER CONTEXT:\n"
        f"Org email: {ctx.get('org_email', 'unknown')}\n"
        f"Office hours: {ctx['office_hours']['start']} - {ctx['office_hours']['end']} IST\n"
        f"Working days: {', '.join(ctx.get('working_days', []))}\n"
        f"Current date/time (IST): {now_ist.strftime('%Y-%m-%d %H:%M %Z, %A')}\n"
        + "\n".join(github_lines) + "\n"
    )

    ALL_TOOLS = CALENDAR_TOOLS + GITHUB_TOOLS

    try:
        response = await client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT + context_note,
            messages=session["messages"],
            tools=ALL_TOOLS,
        )

        # Tool use loop
        while response.stop_reason == "tool_use":
            # Collect all tool calls from this response
            tool_results = []
            last_tool_name = None
            last_result_json = None
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    logger.info("Tool call: %s input=%s", block.name, block.input)
                    result_json = await _dispatch_tool(chat_id, block.name, block.input)
                    last_tool_name = block.name
                    last_result_json = result_json
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_json,
                    })

            # Append assistant turn (with tool_use blocks) then tool results
            append_message(session, "assistant", _normalize_content_blocks(response.content))
            append_message(session, "user", tool_results)

            try:
                response = await client.messages.create(
                    model=ANTHROPIC_MODEL,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT + context_note,
                    messages=session["messages"],
                    tools=ALL_TOOLS,
                )
            except Exception as exc:
                logger.warning("Falling back to Claude synthesis after tool execution error: %s", exc)
                try:
                    synthesized = await _synthesize_tool_reply(
                        client,
                        SYSTEM_PROMPT + context_note,
                        user_message,
                        tool_results,
                    )
                    if synthesized:
                        append_message(session, "assistant", synthesized)
                        save_session(chat_id, session)
                        return synthesized
                except Exception as synth_exc:
                    logger.warning("Claude synthesis fallback failed: %s", synth_exc)
                fallback = (
                    _tool_fallback_reply(last_tool_name, last_result_json)
                    if last_tool_name and last_result_json
                    else None
                )
                if fallback:
                    append_message(session, "assistant", fallback)
                    save_session(chat_id, session)
                    return fallback
                raise

        reply_text = extract_text_reply(response)
        if not reply_text and 'tool_results' in locals() and tool_results:
            try:
                reply_text = await _synthesize_tool_reply(
                    client,
                    SYSTEM_PROMPT + context_note,
                    user_message,
                    tool_results,
                )
            except Exception as synth_exc:
                logger.warning("Claude synthesis fallback failed: %s", synth_exc)
        if not reply_text and 'last_tool_name' in locals() and 'last_result_json' in locals():
            fallback = _tool_fallback_reply(last_tool_name, last_result_json) if last_tool_name and last_result_json else None
            if fallback:
                reply_text = fallback
        append_message(session, "assistant", reply_text)

        new_state = _infer_state_from_reply(reply_text)
        if new_state:
            session["state"] = new_state

        save_session(chat_id, session)
        return reply_text

    except anthropic.AuthenticationError:
        logger.error("Invalid Anthropic API key for chat_id=%s", chat_id)
        return "Your API key is invalid. Type /start to re-enter it."
    except anthropic.APIConnectionError as exc:
        logger.error("API connection error: %s", exc)
        return "Could not reach the AI service. Please try again."
    except anthropic.APIStatusError as exc:
        logger.error("API status error %s: %s", exc.status_code, exc.message)
        return "Something went wrong. Please try again."
    except Exception as exc:
        logger.exception("Unexpected error in run_agent_turn: %s", exc)
        return "Something went wrong. Please try again."
