import os

TIMEZONE = "Asia/Kolkata"  # IST
DEFAULT_OFFICE_START = "09:00"
DEFAULT_OFFICE_END = "18:00"
DEFAULT_WORKING_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
FALLBACK_DELTAS_MINUTES = [-15, +15, -30, +30]  # order matters, agent tries in sequence
MAX_DAYS_TO_SCAN_FORWARD = 5  # how many days ahead to check if current day has no slot
SLOT_GRANULARITY_MINUTES = 15  # free slot grid resolution

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
