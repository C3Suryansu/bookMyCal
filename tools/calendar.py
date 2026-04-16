import re
from datetime import date, datetime, timedelta

import pytz

from config import FALLBACK_DELTAS_MINUTES, SLOT_GRANULARITY_MINUTES

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.utc

_DAY_MAP = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
    "monday": "Monday",
    "tuesday": "Tuesday",
    "wednesday": "Wednesday",
    "thursday": "Thursday",
    "friday": "Friday",
    "saturday": "Saturday",
    "sunday": "Sunday",
}

_WEEKDAY_INDEX = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def parse_office_hours(raw: str) -> dict:
    """Parse '9am-6pm' or '9:00-18:00' or '9am to 6pm' into {"start": "09:00", "end": "18:00"}."""
    raw = raw.strip().lower()
    # Normalise separators: "to", "-", " - "
    raw = re.sub(r"\s*to\s*|\s*-\s*", "-", raw)
    parts = raw.split("-")
    if len(parts) != 2:
        raise ValueError(f"Cannot parse office hours: {raw!r}")

    def _parse_time(s: str) -> str:
        s = s.strip()
        # "9am", "9:30am", "18:00", "9"
        match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", s)
        if not match:
            raise ValueError(f"Cannot parse time: {s!r}")
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    return {"start": _parse_time(parts[0]), "end": _parse_time(parts[1])}


def parse_working_days(raw: str) -> list:
    """Parse 'Mon to Fri' or 'Monday, Tuesday, ...' into list of full day names."""
    raw = raw.strip().lower()
    # Handle range: "mon to fri", "monday to friday"
    range_match = re.match(r"(\w+)\s+to\s+(\w+)", raw)
    if range_match:
        start_key = range_match.group(1)
        end_key = range_match.group(2)
        start_day = _DAY_MAP.get(start_key)
        end_day = _DAY_MAP.get(end_key)
        if not start_day or not end_day:
            raise ValueError(f"Cannot parse day range: {raw!r}")
        ordered = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        si = ordered.index(start_day)
        ei = ordered.index(end_day)
        return ordered[si : ei + 1]

    # Handle comma-separated list
    tokens = re.split(r"[,\s]+", raw)
    days = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        day = _DAY_MAP.get(token)
        if day:
            days.append(day)
    if not days:
        raise ValueError(f"Cannot parse working days: {raw!r}")
    return days


def get_working_days_for_week(target_date: date, working_days: list) -> list:
    """Return list of working day dates in the same Mon–Sun week as target_date."""
    monday = target_date - timedelta(days=target_date.weekday())
    result = []
    for i in range(7):
        d = monday + timedelta(days=i)
        day_name = d.strftime("%A")
        if day_name in working_days:
            result.append(d)
    return result


def ist_to_utc(time_str: str, date_str: str) -> str:
    """Convert HH:MM IST on YYYY-MM-DD to UTC ISO string."""
    hour, minute = map(int, time_str.split(":"))
    year, month, day = map(int, date_str.split("-"))
    naive = datetime(year, month, day, hour, minute)
    ist_dt = IST.localize(naive)
    utc_dt = ist_dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_to_ist(utc_iso: str) -> str:
    """Convert UTC ISO string to HH:MM IST."""
    # Handle both 'Z' suffix and '+00:00'
    utc_iso = utc_iso.replace("Z", "+00:00")
    utc_dt = datetime.fromisoformat(utc_iso).astimezone(UTC)
    ist_dt = utc_dt.astimezone(IST)
    return ist_dt.strftime("%H:%M")


def build_free_slots(busy_blocks: list, date_str: str, office_hours: dict, duration_mins: int) -> list:
    """
    Given busy blocks (list of {start, end} UTC ISO strings), office hours (IST HH:MM),
    a date, and required duration, return list of free start times as IST HH:MM strings.
    Uses SLOT_GRANULARITY_MINUTES grid.
    """
    year, month, day = map(int, date_str.split("-"))
    office_start_h, office_start_m = map(int, office_hours["start"].split(":"))
    office_end_h, office_end_m = map(int, office_hours["end"].split(":"))

    # Build office window in IST
    window_start = IST.localize(datetime(year, month, day, office_start_h, office_start_m))
    window_end = IST.localize(datetime(year, month, day, office_end_h, office_end_m))

    # Parse busy blocks into IST datetimes
    busy = []
    for block in busy_blocks:
        start = datetime.fromisoformat(block["start"].replace("Z", "+00:00")).astimezone(IST)
        end = datetime.fromisoformat(block["end"].replace("Z", "+00:00")).astimezone(IST)
        # Clamp to office window
        start = max(start, window_start)
        end = min(end, window_end)
        if start < end:
            busy.append((start, end))
    busy.sort()

    # Generate candidate slot start times on granularity grid
    free_slots = []
    cursor = window_start
    granularity = timedelta(minutes=SLOT_GRANULARITY_MINUTES)
    duration_td = timedelta(minutes=duration_mins)

    while cursor + duration_td <= window_end:
        slot_end = cursor + duration_td
        # Check if this slot overlaps any busy block
        is_free = True
        for b_start, b_end in busy:
            if cursor < b_end and slot_end > b_start:
                is_free = False
                break
        if is_free:
            free_slots.append(cursor.strftime("%H:%M"))
        cursor += granularity

    return free_slots


def intersect_slots(slots_a: list, slots_b: list, duration_mins: int) -> list:
    """Return common free slots from two free-slot lists (both are HH:MM IST strings)."""
    set_b = set(slots_b)
    return [s for s in slots_a if s in set_b]


def next_fallback_delta(delta_tried: list) -> int | None:
    """
    Returns next delta to try from FALLBACK_DELTAS_MINUTES not yet in delta_tried.
    Returns None if all deltas exhausted.
    """
    for delta in FALLBACK_DELTAS_MINUTES:
        if delta not in delta_tried:
            return delta
    return None
