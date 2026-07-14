"""
Google Calendar sync for the reading bot.

Required env vars:
  GCAL_CREDENTIALS_FILE  path to service-account JSON key
                         (default: /data/gcal-credentials.json)
  GCAL_CALENDAR_ID       the calendar ID to write to — find it in
                         Google Calendar → Settings → [calendar name]
                         → Calendar ID  (looks like xxx@group.calendar.google.com)

If either is missing or the credentials file doesn't exist the module
silently no-ops so the bot works fine without calendar integration.

Color assignments (visible on Skylight):
  Alex  → Blueberry  (deep blue)
  Sam  → Tomato     (red)
  Family / milestone / weekly → Banana (yellow)
"""
import os, re
from datetime import date, timedelta
from pathlib import Path

GCAL_CREDENTIALS_FILE = os.environ.get("GCAL_CREDENTIALS_FILE", "/data/gcal-credentials.json")
GCAL_CALENDAR_ID      = os.environ.get("GCAL_CALENDAR_ID", "")

_COLOR = {
    "alex": "9",   # Blueberry
    "sam": "11",  # Tomato
    "family":  "5",   # Banana
}

_svc = None


def _service():
    global _svc
    if _svc is not None:
        return _svc
    if not GCAL_CALENDAR_ID:
        return None
    creds_path = Path(GCAL_CREDENTIALS_FILE)
    if not creds_path.exists():
        print(f"[gcal] Credentials file not found: {creds_path} — calendar sync disabled")
        return None
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        creds = Credentials.from_service_account_file(
            str(creds_path),
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        _svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
        print("[gcal] Google Calendar service initialized ✓")
        return _svc
    except Exception as e:
        print(f"[gcal] Init failed: {e}")
        return None


def _next_day(d: date) -> str:
    return (d + timedelta(days=1)).isoformat()


def _insert(event: dict) -> str | None:
    """Insert an event and return its Google Calendar event ID, or None on failure."""
    svc = _service()
    if svc is None:
        return None
    try:
        result = svc.events().insert(calendarId=GCAL_CALENDAR_ID, body=event).execute()
        return result.get("id")
    except Exception as e:
        print(f"[gcal] Insert failed: {e}")
        return None


def _patch(gcal_id: str, event: dict) -> bool:
    """Patch (update) an existing event by ID."""
    svc = _service()
    if svc is None:
        return False
    try:
        svc.events().patch(calendarId=GCAL_CALENDAR_ID, eventId=gcal_id, body=event).execute()
        return True
    except Exception as e:
        print(f"[gcal] Patch failed: {e}")
        return False


def _upsert(event_type: str, reader: str, day: date, event: dict) -> bool:
    """
    Insert or update a daily/weekly calendar event.
    Uses db.get/set_gcal_event_id to track the event ID so we can patch it
    on subsequent calls for the same (type, reader, date).
    """
    import db
    date_str  = day.isoformat()
    existing_id = db.get_gcal_event_id(event_type, reader, date_str)

    if existing_id:
        ok = _patch(existing_id, event)
        if ok:
            return True
        # If patch fails (e.g. event was manually deleted), fall through to insert

    new_id = _insert(event)
    if new_id:
        db.set_gcal_event_id(event_type, reader, date_str, new_id)
        return True
    return False


# ── Public API ────────────────────────────────────────────────────────────────

def post_daily_summary(
    reader: str, pts: float, pages: int, streak: int, day: date
) -> bool:
    """Upsert an all-day event with the day's running reading total."""
    streak_str = f" · 🔥 {streak}d streak" if streak >= 2 else ""
    title = f"📖 {reader.capitalize()}: {int(pts)} pts · {pages}p{streak_str}"
    desc  = (
        f"Reading summary for {reader.capitalize()}\n"
        f"Points:  {pts:.1f}\n"
        f"Pages:   {pages}"
    )
    return _upsert("daily", reader, day, {
        "summary":     title,
        "description": desc,
        "start":       {"date": day.isoformat()},
        "end":         {"date": _next_day(day)},
        "colorId":     _COLOR.get(reader, "0"),
    })


def post_weekly_summary(reader_pts, week_label: str, day: date) -> bool:
    """Upsert the weekly recap event (keyed to Sunday's date).

    reader_pts: list of (name, pts) for each reader, in reader order.
    """
    reader_pts = list(reader_pts)
    top = max((p for _, p in reader_pts), default=0)
    leaders = [n for n, p in reader_pts if p == top]
    if not reader_pts or top <= 0:
        winner = ""
    elif len(leaders) > 1:
        winner = " · Tie!"
    else:
        winner = f" · {leaders[0]} wins! 🏅"
    short    = " / ".join(f"{n[0]}:{int(p)}" for n, p in reader_pts)
    combined = sum(p for _, p in reader_pts)
    title = f"📊 {week_label} — {short}{winner}"
    desc  = ("Weekly Reading Summary\n"
             + "\n".join(f"{n}: {p:.1f} pts" for n, p in reader_pts)
             + f"\nCombined: {combined:.1f} pts")
    return _upsert("weekly", "", day, {
        "summary":     title,
        "description": desc,
        "start":       {"date": day.isoformat()},
        "end":         {"date": _next_day(day)},
        "colorId":     _COLOR["family"],
    })


def post_family_goal(pct: int, combined_pts: float, goal: int, day: date) -> bool:
    """All-day event when the family crosses a goal percentage threshold."""
    title = f"🏆 Family goal {pct}% reached: {int(combined_pts):,} / {goal:,} pts"
    desc  = (
        f"Family reading goal progress\n"
        f"Combined points: {combined_pts:.1f}\n"
        f"Goal: {goal}\n"
        f"Progress: {pct}%"
    )
    gcal_id = _insert({
        "summary":     title,
        "description": desc,
        "start":       {"date": day.isoformat()},
        "end":         {"date": _next_day(day)},
        "colorId":     _COLOR["family"],
    })
    return gcal_id is not None


def post_bingo_line(reader: str, line_label: str, square_labels: list,
                    total_pts: float, day: date, bonus: int = 25) -> bool:
    """All-day event when a bingo line is completed."""
    title = f"✨ {reader.capitalize()} — Bingo! {line_label}"
    desc  = (
        f"Bingo line completed!\n"
        f"Squares: {' → '.join(square_labels)}\n"
        f"Bonus: +{bonus} pts\n"
        f"{reader.capitalize()}'s total: {total_pts:.1f} pts"
    )
    gcal_id = _insert({
        "summary":     title,
        "description": desc,
        "start":       {"date": day.isoformat()},
        "end":         {"date": _next_day(day)},
        "colorId":     _COLOR.get(reader, "0"),
    })
    return gcal_id is not None


def post_milestone(reader: str, message: str, total_pts: float, day: date) -> bool:
    """All-day event when a reader crosses a milestone threshold."""
    clean = re.sub(r"[*_`]", "", message).strip()
    title = f"🏆 {reader.capitalize()} — {clean}"
    desc  = f"Milestone reached!\nTotal points: {total_pts:.1f}"
    gcal_id = _insert({
        "summary":     title,
        "description": desc,
        "start":       {"date": day.isoformat()},
        "end":         {"date": _next_day(day)},
        "colorId":     _COLOR["family"],
    })
    return gcal_id is not None
