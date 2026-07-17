"""Reading Bot — Mattermost slash command handler + Summer Reading game board."""

import json, os, re, hmac

from contextlib import asynccontextmanager

from datetime import date, datetime, timedelta, timezone

from pathlib import Path

from fastapi import FastAPI, Request

from fastapi.responses import JSONResponse, FileResponse, RedirectResponse

try:

    from zoneinfo import ZoneInfo

except ImportError:

    ZoneInfo = None


import scoring, db, gcal, bingo as bingo_mod

from parser import parse_read_command, normalize, MAX_PAGES

from rapidfuzz import process, fuzz

# ---------------------------------------------------------------------------

# Config

# ---------------------------------------------------------------------------


MILESTONE_THRESHOLDS = [
    (1500, "🎉 **1,500 points!** Small reward unlocked!"),
    (3000, "🏆 **3,000 points!** Medium reward unlocked!"),
    (4500, "🌟 **4,500 points!** BIG reward unlocked!"),
]

MILESTONE_PTS = [t for t, _ in MILESTONE_THRESHOLDS]

MILESTONE_LABELS = ["Small reward", "Medium reward", "Big reward"]


FAMILY_GOAL = int(os.environ.get("FAMILY_GOAL", "10000"))

FAMILY_GOAL_PCT_MILESTONES = [25, 50, 75, 100]


SLASH_TOKEN_READ = os.environ.get("SLASH_TOKEN_READ", "")

SLASH_TOKEN_READING = os.environ.get("SLASH_TOKEN_READING", "")

SLASH_TOKEN_BOOK = os.environ.get("SLASH_TOKEN_BOOK", "")

SLASH_TOKEN_BINGO = os.environ.get("SLASH_TOKEN_BINGO", "")

# Set ALEXA_SKILL_ID in the environment to enable the Alexa skill. Empty by
# default so the /alexa endpoint is effectively disabled until a deployment
# configures its own skill (no household-specific ID shipped in the repo).
ALEXA_SKILL_ID = os.environ.get("ALEXA_SKILL_ID", "")

TZ_LOCAL = os.environ.get("TZ_LOCAL", "America/New_York")


# Summer date window for the board

SUMMER_START = os.environ.get("SUMMER_START", "2026-06-01")

SUMMER_END = os.environ.get("SUMMER_END", "2026-08-31")


# Derived from the single readers config so the board renders whoever is
# configured. Same fields as before (no leakage of the extra 'level' key).
from readers import READERS, READER_KEYS, resolve_reader, get_reader

PLAYERS_CONFIG = [
    {
        "key": r["key"],
        "name": r["name"],
        "monogram": r["monogram"],
        "age": r["age"],
        "grade": r["grade"],
    }
    for r in READERS
]


BOARD_DIR = Path(__file__).parent / "board"


# ---------------------------------------------------------------------------

# Book database

# ---------------------------------------------------------------------------

BOOKS_FILE = Path(__file__).parent / "books.json"

_BUILTIN_BOOKS: list[dict] = json.loads(BOOKS_FILE.read_text())


def _all_books() -> list[dict]:

    return _BUILTIN_BOOKS + db.get_custom_books()


def _build_index(books: list[dict]) -> dict[str, dict]:

    idx: dict[str, dict] = {}
    for book in books:
        idx[book["key"]] = book
        idx[normalize(book["title"])] = book
        for alias in book.get("aliases", []):
            idx[normalize(alias)] = book
    return idx


def _book_by_key_index() -> dict[str, dict]:

    return {b["key"]: b for b in _all_books()}


def find_book(query: str):

    books = _all_books()
    idx = _build_index(books)
    norm_q = normalize(query)
    if norm_q in idx:
        return idx[norm_q], 100
    result = process.extractOne(
        norm_q, list(idx.keys()), scorer=fuzz.token_set_ratio, score_cutoff=72
    )
    if result is None:
        return None, 0
    matched_alias, score, _ = result
    return idx[matched_alias], score


# ---------------------------------------------------------------------------

# Helpers

# ---------------------------------------------------------------------------


def fmt_pts(pts: float) -> str:

    return f"{pts:.1f}" if pts != int(pts) else str(int(pts))


def check_milestones(reader: str, prev: float, new: float) -> list[str]:

    return [msg for threshold, msg in MILESTONE_THRESHOLDS if prev < threshold <= new]


def check_family_goal(prev_combined: float, new_combined: float) -> list[int]:

    hit = []
    for pct in FAMILY_GOAL_PCT_MILESTONES:
        threshold = FAMILY_GOAL * pct / 100
        if prev_combined < threshold <= new_combined:
            hit.append(pct)
    return hit


def _in_channel(text: str):

    return JSONResponse({"response_type": "in_channel", "text": text})


def _ephemeral(text: str):

    return JSONResponse({"response_type": "ephemeral", "text": text})


def _valid_slash_token(form, expected: str) -> bool:
    """Constant-time check of the Mattermost slash-command token.

    If no token is configured for a command (expected == ""), the check is
    skipped so the command keeps working — but that means it's unauthenticated,
    so keep the SLASH_TOKEN_* env vars set. Returns True when the request is
    allowed to proceed.
    """
    if not expected:
        return True
    supplied = form.get("token") or ""
    return hmac.compare_digest(str(supplied), str(expected))


def _process_bingo(
    reader: str,
    session_pages: int,
    session_minutes: int,
    book: dict,
    finished: bool,
    book_key: str,
    session_date: str,
    audiobook: bool = False,
) -> list[str]:
    # Audiobooks don't count toward bingo — listening, not reading.
    if audiobook:
        return []
    extra_lines = []
    # IMPORTANT: pass session_date (already localized via _today()) into the
    # db queries so they don't fall back to date.today() — which is UTC inside
    # the container and silently reads from the wrong day after ~8pm Eastern.
    today_local = date.fromisoformat(session_date)
    daily_pages = db.get_daily_stats(reader, session_date)["pages"]
    books_finished_week = db.get_books_finished_this_week(reader, today=today_local)
    book_first_date = db.get_book_first_session_date(reader, book_key)
    book_total_pages = db.get_book_total_pages(reader, book_key)
    card_num = db.get_bingo_card_num(reader)
    books_finished_total = _books_finished_count(reader)
    triggers = bingo_mod.auto_detect(
        reader,
        session_pages,
        session_minutes,
        daily_pages,
        book,
        finished,
        book_first_date,
        session_date,
        books_finished_week,
        book_total_pages=book_total_pages,
        card_num=card_num,
        books_finished_total=books_finished_total,
    )
    newly_checked = []
    for square_id, reason in triggers:
        label = bingo_mod.square_label(reader, square_id, card_num)
        if db.bingo_check(reader, square_id, "auto", reason):
            extra_lines.append(f"🎯 Bingo auto-check: **{label}**")
            newly_checked.append(square_id)
    if newly_checked:
        _award_bingo_lines(reader, extra_lines, session_date, card_num=card_num)
    return extra_lines


def _award_bingo_lines(
    reader: str, out_lines: list[str], session_date: str = None, card_num: int = 1
):

    checked = db.bingo_get_checked(reader)
    already = db.bingo_get_lines_awarded(reader)
    new_lines = bingo_mod.check_new_lines(reader, checked, already, card_num=card_num)
    for line_id, line_label, square_labels in new_lines:
        bonus = bingo_mod.line_bonus(card_num)
        db.bingo_award_line(reader, line_id)
        db.add_bingo_points(reader, bonus, f"Bingo {line_label}", session_date=session_date)
        total = db.get_total_stats(reader)["pts"]
        squares_str = " → ".join(square_labels)
        out_lines.append(f"✨ **Bingo line complete! +{bonus} pts** " f"({line_label})")
        out_lines.append(f"  {squares_str}")
        out_lines.append(f"  {reader.capitalize()}'s new total: **{fmt_pts(total)} pts**")
        gcal_day = date.fromisoformat(session_date) if session_date else _today()
        gcal.post_bingo_line(reader, line_label, square_labels, total, gcal_day, bonus=bonus)
    # ── Card-complete check ────────────────────────────────────────────────
    awarded_now = db.bingo_get_lines_awarded(reader)
    if len(awarded_now) >= bingo_mod.total_lines():
        new_card = db.increment_bingo_card(reader)
        next_bonus = bingo_mod.line_bonus(new_card)
        # Re-init free square on new card
        free_id = bingo_mod.get_free_square(reader, new_card)
        if free_id:
            db.bingo_init(reader, {free_id})
        total_pts = db.get_total_stats(reader)["pts"]
        out_lines.append("")
        out_lines.append(
            f"🎉 **BINGO CARD #{card_num} COMPLETE!** {reader.capitalize()} finished every line!"
        )
        out_lines.append(f"  Starting Card #{new_card} — each line now worth **{next_bonus} pts**!")
        out_lines.append(f"  {reader.capitalize()}'s total: **{fmt_pts(total_pts)} pts**")


def _post_realtime_summaries(reader: str, today: date):

    stats = db.get_daily_stats(reader, today.isoformat())
    streak = db.get_streak(reader, today=today)
    gcal.post_daily_summary(reader, stats["pts"], stats["pages"], streak, today)
    days_until_sunday = (6 - today.weekday()) % 7
    sunday = today + timedelta(days=days_until_sunday)
    week_num = today.isocalendar()[1]
    reader_pts = [
        (get_reader(k)["name"], db.get_weekly_stats(k, today=today)["pts"]) for k in READER_KEYS
    ]
    if any(p > 0 for _, p in reader_pts):
        gcal.post_weekly_summary(reader_pts, f"Week {week_num}", sunday)


@asynccontextmanager
async def _lifespan(app: FastAPI):

    db.init_db()
    for _reader in READER_KEYS:
        _card_n = db.get_bingo_card_num(_reader)
        _free = bingo_mod.get_free_square(_reader, _card_n)
        if _free:
            db.bingo_init(_reader, {_free})
    yield


# ---------------------------------------------------------------------------

# App

# ---------------------------------------------------------------------------

app = FastAPI(title="Reading Bot", lifespan=_lifespan)


@app.get("/health")
def health():

    return {"status": "ok", "books": len(_BUILTIN_BOOKS)}


# ===========================================================================

# Summer Reading game board — /board, /board/ipad, /board.json

# ===========================================================================


def _local_tz():

    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(TZ_LOCAL)
    except Exception:
        return timezone.utc


def _today() -> date:
    """Current date in the configured local timezone (not UTC)."""
    try:
        return datetime.now(_local_tz()).date()
    except Exception:
        return date.today()


_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_DAY_ABBREVS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_session_date(raw: str | None, today: date) -> date | None:
    """Resolve a date string from /read date= param to a date object.
    Supports: YYYY-MM-DD, 'today', 'yesterday', day names or 3-letter
    abbreviations (e.g. 'saturday'/'sat' = most recent past Saturday).
    Returns None if the value can't be parsed or is in the future —
    silently logging on the wrong day is worse than an error.
    """
    if raw is None:
        return today
    raw = raw.lower().strip()
    if raw == "today":
        return today
    if raw == "yesterday":
        return today - timedelta(days=1)
    target_dow = None
    if raw in _DAY_NAMES:
        target_dow = _DAY_NAMES.index(raw)
    elif raw in _DAY_ABBREVS:
        target_dow = _DAY_ABBREVS.index(raw)
    if target_dow is not None:
        delta = (today.weekday() - target_dow) % 7
        if delta == 0:
            delta = 7  # "saturday" when today IS saturday means last Saturday
        return today - timedelta(days=delta)
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return None
    if d > today:
        return None
    return d


_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _fmt_short_date(d: date) -> str:

    return f"{_MONTH_ABBR[d.month-1]} {d.day}"


def _fmt_today_label(d: date) -> str:

    return f"{_DAY_SHORT[d.weekday()]}, {_MONTH_ABBR[d.month-1]} {d.day}"


def _fmt_local_time(iso_utc: str) -> str:

    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(_local_tz())
        h = local.hour % 12 or 12
        ampm = "p" if local.hour >= 12 else "a"
        return f"{h}:{local.minute:02d}{ampm}"
    except Exception:
        return ""


def _when_label(sess_date: date, today: date) -> str:

    delta = (today - sess_date).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yest"
    if 0 < delta < 7:
        return _DAY_SHORT[sess_date.weekday()]
    return _fmt_short_date(sess_date)


def _books_finished_count(reader: str, since: str = None) -> int:
    """Count distinct book_keys where any session is finished=1."""
    with db.get_conn() as conn:
        try:
            if since:
                row = conn.execute(
                    "SELECT COUNT(DISTINCT book_key) AS n FROM sessions "
                    "WHERE reader=? AND finished=1 AND book_key != 'bingo-bonus' "
                    "AND session_date >= ?",
                    (reader, since),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(DISTINCT book_key) AS n FROM sessions "
                    "WHERE reader=? AND finished=1 AND book_key != 'bingo-bonus'",
                    (reader,),
                ).fetchone()
            return int(row["n"])
        except Exception:
            return 0


def _recent_sessions_enriched(
    reader: str, limit: int = 3, book_idx: dict = None, since: str = None
) -> list[dict]:
    """Pull recent sessions with extra fields the board needs."""
    if book_idx is None:
        book_idx = _book_by_key_index()
    today = _today()
    with db.get_conn() as conn:
        if since:
            rows = conn.execute(
                """SELECT book_key, book_title, pages, minutes, points, session_date, logged_at

                   FROM sessions

                   WHERE reader=? AND book_key != 'bingo-bonus' AND session_date >= ?

                   ORDER BY logged_at DESC LIMIT ?""",
                (reader, since, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT book_key, book_title, pages, minutes, points, session_date, logged_at

                   FROM sessions

                   WHERE reader=? AND book_key != 'bingo-bonus'

                   ORDER BY logged_at DESC LIMIT ?""",
                (reader, limit),
            ).fetchall()
    out = []
    for s in rows:
        book = book_idx.get(s["book_key"])
        if book is None:
            book, _ = find_book(s["book_title"])
        detail = ""
        if book is not None:
            fmt = book.get("format", "chapter_book")
            if fmt in scoring.SPECIAL_OVERRIDES:
                detail = fmt.replace("_", " ").title()
            else:
                lex = book.get("lexile") or 0
                tier_name, _ = scoring.get_tier(lex, reader)
                tier_label = scoring.TIER_LABELS.get(tier_name, tier_name).title()
                cls = book.get("classification", "standard")
                cls_label = "" if cls == "standard" else f" × {cls.replace('_', ' ').title()}"
                detail = f"{lex}L · {tier_label}{cls_label}" if lex else tier_label
        sess_d = date.fromisoformat(s["session_date"])
        out.append(
            {
                "title": s["book_title"],
                "when_label": _when_label(sess_d, today),
                "when_time": _fmt_local_time(s["logged_at"]),
                "pages": int(s["pages"]),
                "points": float(s["points"]),
                "detail_meta": detail,
            }
        )
    return out


def _avg_ppp(reader: str, since: str = None):
    """Average points-per-page across the season (or all-time if since is None).
    Pages-weighted: total points / total pages. Returns None if no pages logged."""
    q = (
        "SELECT COALESCE(SUM(points),0) AS pts, "
        "       COALESCE(SUM(pages),0)  AS pages "
        "FROM sessions WHERE reader=? AND book_key != 'bingo-bonus' AND pages > 0"
    )
    params = [reader]
    if since:
        q += " AND session_date >= ?"
        params.append(since)
    with db.get_conn() as conn:
        row = conn.execute(q, params).fetchone()
    pages = row["pages"] or 0
    if pages == 0:
        return None
    return float(row["pts"]) / float(pages)


def _build_player(p_cfg: dict, today: date, book_idx: dict, stats_from: str = None) -> dict:

    key = p_cfg["key"]
    daily = db.get_daily_stats(key, today.isoformat())
    weekly = db.get_weekly_stats(key, today=today)
    total = db.get_total_stats(key, since=stats_from)
    # Week breakdown (Mon..Sun)
    week_start = today - timedelta(days=today.weekday())
    by_day = []
    days_read = 0
    for i in range(7):
        d = week_start + timedelta(days=i)
        ds = db.get_daily_stats(key, d.isoformat())
        sessions = int(ds["sessions"])
        if sessions > 0:
            days_read += 1
        by_day.append(
            {
                "name": _DAY_SHORT[i],
                "pages": int(ds["pages"]),
                "sessions": sessions,
                "is_today": d == today,
                "is_future": d > today,
            }
        )
    # Milestones
    cleared = [i for i, pts in enumerate(MILESTONE_PTS) if total["pts"] >= pts]
    next_index = next((i for i, pts in enumerate(MILESTONE_PTS) if total["pts"] < pts), None)
    next_to_go = (MILESTONE_PTS[next_index] - total["pts"]) if next_index is not None else None
    progress_all = min(1.0, float(total["pts"]) / float(MILESTONE_PTS[-1]))
    # Tier chip — season average pts/pg (stable; not reset weekly)
    avg_ppp = _avg_ppp(key, since=stats_from)
    if avg_ppp is None:
        tier_label, tier_ppp_str = "Avg", "—"
    else:
        tier_label, tier_ppp_str = "Avg", f"{avg_ppp:.2f}"
    # Bingo state
    bingo_card_num = db.get_bingo_card_num(key)
    bingo_squares = bingo_mod.get_card_squares(key, bingo_card_num)
    bingo_checked = db.bingo_get_checked(key)
    bingo_awarded = db.bingo_get_lines_awarded(key)
    squares_checked_idx = [i for i, (sid, _) in enumerate(bingo_squares) if sid in bingo_checked]
    bingo_lines_idx = []
    for i, line in enumerate(bingo_mod.BINGO_LINES):
        line_id = f"line_{i}"
        if line_id in bingo_awarded:
            bingo_lines_idx.append(i)
    return {
        "key": key,
        "name": p_cfg["name"],
        "monogram": p_cfg["monogram"],
        "age": p_cfg["age"],
        "grade": p_cfg["grade"],
        "total_pts": float(total["pts"]),
        "books_finished": _books_finished_count(key, since=stats_from),
        "tier_label": tier_label,
        "tier_ppp": tier_ppp_str,
        "today": {
            "pages": int(daily["pages"]),
            "pts": float(daily["pts"]),
            "sessions": int(daily["sessions"]),
        },
        "week": {
            "pts": float(weekly["pts"]),
            "pages": int(weekly["pages"]),
            "days_read": days_read,
            "by_day": by_day,
        },
        "milestones": {
            "cleared_indices": cleared,
            "next_index": next_index,
            "next_to_go": next_to_go,
            "progress_overall": progress_all,
        },
        "bingo": {
            "squares_checked": squares_checked_idx,
            "lines": bingo_lines_idx,
            "lines_count": len(bingo_lines_idx),
            "pts_bonus": len(bingo_lines_idx) * bingo_mod.line_bonus(bingo_card_num),
            "card_num": bingo_card_num,
            "grid_size": 5,
        },
        "recent": _recent_sessions_enriched(key, limit=3, book_idx=book_idx, since=stats_from),
    }


def _build_board_payload() -> dict:

    today = _today()
    summer_start = date.fromisoformat(SUMMER_START)
    summer_end = date.fromisoformat(SUMMER_END)
    total_days = (summer_end - summer_start).days + 1
    day_of_sum = max(1, min(total_days, (today - summer_start).days + 1))
    days_left = max(0, (summer_end - today).days)
    pct = (day_of_sum - 1) / max(1, total_days - 1)
    # Only count summer sessions once summer has started
    stats_from = SUMMER_START if today >= summer_start else None
    book_idx = _book_by_key_index()
    players = [_build_player(cfg, today, book_idx, stats_from=stats_from) for cfg in PLAYERS_CONFIG]
    # Family goal
    per_reader = {k: db.get_total_stats(k, since=stats_from)["pts"] for k in READER_KEYS}
    combined = sum(per_reader.values())
    return {
        "today": {
            "iso": today.isoformat(),
            "label": _fmt_today_label(today),
        },
        "summer": {
            "day": day_of_sum,
            "total": total_days,
            "left": days_left,
            "start_label": _fmt_short_date(summer_start),
            "end_label": _fmt_short_date(summer_end),
            "pct": pct,
        },
        "family_goal": {
            "current": float(combined),
            "target": FAMILY_GOAL,
            "pct": min(combined / FAMILY_GOAL, 1.0),
            **{k: float(per_reader[k]) for k in READER_KEYS},
        },
        "milestones": [{"pts": p, "label": l} for p, l in zip(MILESTONE_PTS, MILESTONE_LABELS)],
        "players": players,
    }


_FORMAT_LABELS = {
    "chapter_book": "Chapter book",
    "early_chapter_book": "Early chapter",
    "dense_middle_grade": "Dense middle grade",
    "dense_classic": "Dense classic",
    "nonfiction": "Nonfiction",
    "graphic_novel": "Graphic novel",
    "graphic_novel_telgemeier": "Graphic novel",
    "easy_reader": "Easy reader",
}

_CLASS_LABELS = {
    "masterpiece": "Masterpiece",
    "modern_classic": "Modern Classic",
    "standard": "",
}


def _build_library_payload() -> dict:

    today = _today()
    book_idx = _book_by_key_index()
    players_out = []
    for p_cfg in PLAYERS_CONFIG:
        reader = p_cfg["key"]
        with db.get_conn() as conn:
            # Totals
            tot = conn.execute(
                """SELECT COUNT(DISTINCT book_key) AS books_total,

                          COUNT(DISTINCT CASE WHEN finished=1 THEN book_key END) AS books_finished,

                          COALESCE(SUM(pages),0)   AS pages,

                          COALESCE(SUM(points),0)  AS points,

                          COUNT(*) AS sessions

                   FROM sessions WHERE reader=? AND book_key != 'bingo-bonus'""",
                (reader,),
            ).fetchone()
            # Per-book rows
            rows = conn.execute(
                """SELECT book_key, book_title,

                          COALESCE(SUM(pages),0)   AS pages_read,

                          COALESCE(SUM(points),0)  AS points_earned,

                          COUNT(*)                 AS sessions,

                          MAX(finished)            AS finished,

                          MAX(CASE WHEN finished=1 THEN session_date END) AS finished_date,

                          MIN(session_date)         AS first_session,

                          MAX(session_date)         AS last_session

                   FROM sessions

                   WHERE reader=? AND book_key != 'bingo-bonus'

                   GROUP BY book_key, book_title

                   ORDER BY MAX(session_date) DESC""",
                (reader,),
            ).fetchall()
        books_out = []
        for row in rows:
            bk = book_idx.get(row["book_key"])
            lexile = bk.get("lexile") if bk else None
            fmt = (bk.get("format") if bk else None) or "chapter_book"
            cls = (bk.get("classification") if bk else None) or "standard"
            il = (bk.get("interest_level") if bk else None) or ""
            ppp_result = scoring.compute_points(bk or {}, reader, 1) if bk else None
            tier_label = scoring.TIER_LABELS.get(ppp_result["tier"], "") if ppp_result else ""
            ppp = ppp_result["ppp"] if ppp_result else 0.0
            books_out.append(
                {
                    "key": row["book_key"],
                    "title": row["book_title"],
                    "lexile": lexile,
                    "format": fmt,
                    "format_label": _FORMAT_LABELS.get(fmt, fmt.replace("_", " ").title()),
                    "classification": cls,
                    "classification_label": _CLASS_LABELS.get(cls, cls),
                    "interest_level": il,
                    "tier_label": tier_label,
                    "pts_per_page": ppp,
                    "pages_read": int(row["pages_read"]),
                    "points_earned": float(row["points_earned"]),
                    "sessions": int(row["sessions"]),
                    "finished": bool(row["finished"]),
                    "finished_date": row["finished_date"],
                    "first_session": row["first_session"],
                    "last_session": row["last_session"],
                }
            )
        players_out.append(
            {
                "key": p_cfg["key"],
                "name": p_cfg["name"],
                "monogram": p_cfg["monogram"],
                "age": p_cfg["age"],
                "grade": p_cfg["grade"],
                "totals": {
                    "books_total": int(tot["books_total"]),
                    "books_finished": int(tot["books_finished"]),
                    "pages": int(tot["pages"]),
                    "points": float(tot["points"]),
                    "sessions": int(tot["sessions"]),
                },
                "books": books_out,
            }
        )
    return {
        "today": {
            "iso": today.isoformat(),
            "label": _fmt_today_label(today),
        },
        "players": players_out,
    }


@app.get("/board", include_in_schema=False)
async def board_redirect():

    return RedirectResponse(url="/board/", status_code=307)


@app.get("/board/", include_in_schema=False)
async def board_desktop():

    return FileResponse(BOARD_DIR / "index.html", media_type="text/html")


@app.get("/board/ipad", include_in_schema=False)
async def board_ipad():

    return FileResponse(BOARD_DIR / "ipad.html", media_type="text/html")


@app.get("/board/board.js", include_in_schema=False)
async def board_js():

    return FileResponse(
        BOARD_DIR / "board.js",
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=60"},
    )


@app.get("/library", include_in_schema=False)
@app.get("/library/", include_in_schema=False)
async def library_redirect():
    return RedirectResponse(url="/board/library", status_code=301)


@app.get("/board/library", include_in_schema=False)
async def board_library():
    return FileResponse(BOARD_DIR / "library.html", media_type="text/html")


@app.get("/board.json")
async def board_json():

    payload = _build_board_payload()
    return JSONResponse(payload, headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/library.json")
async def library_json():

    payload = _build_library_payload()
    return JSONResponse(payload, headers={"Cache-Control": "no-store, must-revalidate"})


# ===========================================================================

# /read  — log a session   (unchanged from live app)

# ===========================================================================

# ===========================================================================
# Web logging API — lets you log reading from the browser (the /log page),
# so Mattermost is optional. Reuses the same scoring/db helpers the slash
# commands use. Optional LOG_PIN gates writes for internet-exposed deploys.
# ===========================================================================
LOG_PIN = os.environ.get("LOG_PIN", "")

_WEB_FORMATS = [
    {"value": "chapter_book", "label": "Chapter book", "needs_lexile": True},
    {"value": "early_chapter_book", "label": "Early chapter book", "needs_lexile": False},
    {"value": "graphic_novel", "label": "Graphic novel", "needs_lexile": False},
    {"value": "easy_reader", "label": "Easy reader", "needs_lexile": False},
    {"value": "picture_book", "label": "Picture book", "needs_lexile": False},
    {"value": "nonfiction", "label": "Nonfiction", "needs_lexile": True},
    {"value": "dense_middle_grade", "label": "Dense middle-grade", "needs_lexile": True},
    {"value": "dense_classic", "label": "Dense classic", "needs_lexile": True},
]
_VALID_FORMATS = {f["value"] for f in _WEB_FORMATS}


def _plain(s: str) -> str:
    """Strip Markdown emphasis so a slash-style message reads cleanly as text."""
    return re.sub(r"\*\*|\*|`|_", "", s or "").strip()


def _log_pin_ok(request: Request, body: dict) -> bool:
    if not LOG_PIN:
        return True
    supplied = (
        request.headers.get("X-Log-Pin")
        or (body.get("pin") if isinstance(body, dict) else "")
        or ""
    )
    return hmac.compare_digest(str(supplied), LOG_PIN)


def _book_by_key(key: str):
    for b in _all_books():
        if b.get("key") == key:
            return b
    return None


def resolve_book_for_log(book_raw: str, fmt_hint, inline_lexile):
    """Non-interactive book resolution for the web form.

    Returns (book, None) if resolved, or (None, needs_dict) when a new book
    needs a format (and Lexile) from the user before it can be added.
    """
    book, _ = find_book(book_raw)
    if book is not None:
        return book, None
    title = book_raw.strip()
    key = re.sub(r"\s+", "-", normalize(book_raw))[:40]
    if fmt_hint not in _VALID_FORMATS:
        return None, {
            "reason": "new_book",
            "title": title,
            "message": f"“{title}” isn’t in the catalog yet — pick a format to add it.",
        }
    needs_lex = next((f["needs_lexile"] for f in _WEB_FORMATS if f["value"] == fmt_hint), False)
    if needs_lex and inline_lexile is None:
        return None, {
            "reason": "need_lexile",
            "title": title,
            "format": fmt_hint,
            "message": f"“{title}” needs a Lexile (look it up at hub.lexile.com, or estimate).",
        }
    lex = inline_lexile if needs_lex else None
    db.add_custom_book(key, title, lex, fmt_hint, "standard", [normalize(title)])
    return {
        "key": key,
        "title": title,
        "lexile": lex or 0,
        "format": fmt_hint,
        "classification": "standard",
    }, None


def perform_log(
    reader, book, pages, minutes, finished, audiobook, session_date_local, today_local
) -> dict:
    """Shared logging core: score, persist, run milestone/family/bingo side
    effects + calendar sync, and return a structured result. Used by the web
    API; mirrors what the /read slash handler does."""
    ug_warning = None
    _rcfg = get_reader(reader)
    if _rcfg and _rcfg.get("warn_upper_grade") and book.get("interest_level") == "UG":
        ug_warning = (
            f"{book['title']} is tagged for upper grades (9+). "
            "Make sure a parent has previewed the content."
        )
    result = scoring.compute_points(book, reader, pages, audiobook=audiobook)
    ppp, points = result["ppp"], result["points"]
    prev_combined = sum(db.get_total_stats(k)["pts"] for k in READER_KEYS)
    prev_total = db.get_total_stats(reader)["pts"]
    db.log_session(
        reader,
        book["key"],
        book["title"],
        pages,
        minutes,
        ppp,
        points,
        finished=finished,
        session_date=session_date_local.isoformat(),
        audiobook=audiobook,
    )
    daily = db.get_daily_stats(reader, session_date_local.isoformat())
    weekly = db.get_weekly_stats(reader, today=session_date_local)
    total = db.get_total_stats(reader)
    events = []
    for msg in check_milestones(reader, prev_total, total["pts"]):
        gcal.post_milestone(reader, msg, total["pts"], session_date_local)
        events.append(_plain(msg))
    new_combined = sum(db.get_total_stats(k)["pts"] for k in READER_KEYS)
    for pct in check_family_goal(prev_combined, new_combined):
        events.append(f"Family goal {pct}% reached: {fmt_pts(new_combined)} / {FAMILY_GOAL} pts!")
        gcal.post_family_goal(pct, new_combined, FAMILY_GOAL, session_date_local)
    for bl in (
        _process_bingo(
            reader,
            pages,
            minutes,
            book,
            finished,
            book["key"],
            session_date_local.isoformat(),
            audiobook=audiobook,
        )
        or []
    ):
        line = _plain(bl)
        if line:
            events.append(line)
    _post_realtime_summaries(reader, today_local)
    backdated = session_date_local != today_local
    if backdated:
        _post_realtime_summaries(reader, session_date_local)
    return {
        "reader": reader,
        "book_title": book["title"],
        "pages": pages,
        "minutes": minutes,
        "finished": finished,
        "audiobook": audiobook,
        "ppp": ppp,
        "points": points,
        "tier": result.get("tier"),
        "tier_label": scoring.TIER_LABELS.get(result.get("tier"), result.get("tier")),
        "lexile": result.get("lexile"),
        "format": result.get("format"),
        "daily_pages": daily["pages"],
        "week_pts": weekly["pts"],
        "total_pts": total["pts"],
        "ug_warning": ug_warning,
        "events": events,
        "backdated": backdated,
        "session_date": session_date_local.isoformat(),
    }


@app.get("/log", include_in_schema=False)
async def log_page():
    return FileResponse(BOARD_DIR / "log.html", media_type="text/html")


@app.get("/api/config", include_in_schema=False)
async def api_config():
    return JSONResponse(
        {
            "readers": PLAYERS_CONFIG,
            "formats": _WEB_FORMATS,
            "pin_required": bool(LOG_PIN),
            "max_pages": MAX_PAGES,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/books", include_in_schema=False)
async def api_books(q: str = "", limit: int = 8):
    q = (q or "").strip()
    if len(q) < 2:
        return JSONResponse([])
    idx = _build_index(_all_books())
    matches = process.extract(
        normalize(q), list(idx.keys()), scorer=fuzz.token_set_ratio, limit=max(limit * 3, 12)
    )
    seen, out = set(), []
    for alias, score, _ in matches:
        b = idx[alias]
        if b["key"] in seen:
            continue
        seen.add(b["key"])
        out.append(
            {
                "key": b["key"],
                "title": b["title"],
                "lexile": b.get("lexile"),
                "format": b.get("format"),
                "classification": b.get("classification"),
            }
        )
        if len(out) >= limit:
            break
    return JSONResponse(out)


@app.post("/api/log", include_in_schema=False)
async def api_log(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Expected a JSON body."}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "Expected a JSON object."}, status_code=400)
    if not _log_pin_ok(request, body):
        return JSONResponse({"ok": False, "error": "Wrong or missing PIN."}, status_code=403)
    # ---- command-bar path: same syntax as the /read slash command ----
    if body.get("command"):
        parsed = parse_read_command(body["command"])
        if "error" in parsed:
            return JSONResponse({"ok": False, "error": _plain(parsed["error"])}, status_code=400)
        reader, pages, minutes = parsed["reader"], parsed["pages"], parsed["minutes"]
        book_raw, fmt_hint = parsed["book_raw"], parsed.get("format_hint")
        finished = parsed.get("finished", False)
        audiobook = parsed.get("audiobook", False)
        date_hint = parsed.get("date")
        m = re.search(r"lexile\s*=\s*(\d+)", body["command"].lower())
        inline_lexile = int(m.group(1)) if m else None
        book_key = None
    # ---- structured-form path ----
    else:
        reader = resolve_reader(body.get("reader", ""))
        if not reader:
            return JSONResponse({"ok": False, "error": "Pick a reader."}, status_code=400)
        try:
            pages = int(body.get("pages"))
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "Enter a page count."}, status_code=400)
        if pages <= 0:
            return JSONResponse(
                {"ok": False, "error": "Pages must be greater than 0."}, status_code=400
            )
        if pages > MAX_PAGES:
            return JSONResponse(
                {
                    "ok": False,
                    "error": f"Pages looks too large (max {MAX_PAGES}) — split into sessions.",
                },
                status_code=400,
            )
        try:
            minutes = int(body.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        book_raw = (body.get("book") or "").strip()
        book_key = (body.get("book_key") or "").strip() or None
        fmt_hint = (body.get("format") or "").strip() or None
        inline_lexile = (
            int(body["lexile"]) if str(body.get("lexile") or "").strip().isdigit() else None
        )
        finished = bool(body.get("finished"))
        audiobook = bool(body.get("audiobook"))
        date_hint = (body.get("date") or "").strip() or None
        if not book_raw and not book_key:
            return JSONResponse({"ok": False, "error": "Pick or type a book."}, status_code=400)
    # ---- resolve the book ----
    if body.get("book_key"):
        book = _book_by_key(body["book_key"])
        if book is None:
            return JSONResponse(
                {"ok": False, "error": "That book is no longer available."}, status_code=400
            )
    else:
        book, needs = resolve_book_for_log(book_raw, fmt_hint, inline_lexile)
        if needs:
            return JSONResponse({"ok": False, "needs": needs})
    today_local = _today()
    session_date_local = _parse_session_date(date_hint, today_local)
    if session_date_local is None:
        return JSONResponse(
            {
                "ok": False,
                "error": f"Couldn’t understand the date (or it’s in the future). Nothing logged.",
            },
            status_code=400,
        )
    res = perform_log(
        reader, book, pages, minutes, finished, audiobook, session_date_local, today_local
    )
    return JSONResponse({"ok": True, **res})


@app.post("/slash/read")
async def slash_read(request: Request):

    form = await request.form()
    if not _valid_slash_token(form, SLASH_TOKEN_READ):
        return _ephemeral("⛔ Unauthorized (invalid slash-command token).")
    text = (form.get("text") or "").strip()
    if not text:
        return _ephemeral(
            'Usage: `/read [alex|sam] "book title" pages=N`\n'
            "Add `finished` when you finish the book · `audiobook` for ¼ points · "
            "`date=yesterday` to backdate."
        )
    parsed = parse_read_command(text)
    if "error" in parsed:
        return _ephemeral(parsed["error"])
    reader = parsed["reader"]
    pages = parsed["pages"]
    minutes = parsed["minutes"]
    book_raw = parsed["book_raw"]
    fmt_hint = parsed.get("format_hint")
    finished = parsed.get("finished", False)
    date_hint = parsed.get("date")
    audiobook = parsed.get("audiobook", False)
    book, score = find_book(book_raw)
    raw_lower = text.lower()
    lex_m = re.search(r"lexile\s*=\s*(\d+)", raw_lower)
    inline_lexile = int(lex_m.group(1)) if lex_m else None
    if book is None:
        safe = book_raw.replace('"', "")
        title = book_raw.strip()
        key = re.sub(r"\s+", "-", normalize(book_raw))[:40]
        if fmt_hint is None and inline_lexile is None:
            return _ephemeral(
                f"📚 I don't recognise **{book_raw}** yet. What format is it?\n"
                f"Reply with one of:\n"
                f'• `/read {reader} "{safe}" pages={pages} format=chapter lexile=750`\n'
                f'• `/read {reader} "{safe}" pages={pages} format=early` _(easy chapter book)_\n'
                f'• `/read {reader} "{safe}" pages={pages} format=graphic`\n'
                f'• `/read {reader} "{safe}" pages={pages} format=easy`\n'
                f"_(Replace 750 with the actual Lexile — look it up at hub.lexile.com)_"
            )
        if fmt_hint is None and inline_lexile is not None:
            fmt_hint = "chapter_book"
        if fmt_hint == "chapter_book" and inline_lexile is None:
            return _ephemeral(
                f"📚 Adding **{title}** as a chapter book — what's the Lexile?\n"
                f'`/read {reader} "{safe}" pages={pages} format=chapter lexile=750`\n'
                f"_(Replace 750 with the real score, or 800 as a default)_"
            )
        if fmt_hint in (
            "chapter_book",
            "early_chapter_book",
            "dense_middle_grade",
            "dense_classic",
            "nonfiction",
        ):
            db.add_custom_book(key, title, inline_lexile, fmt_hint, "standard", [normalize(title)])
            book = {
                "key": key,
                "title": title,
                "lexile": inline_lexile or 0,
                "format": fmt_hint,
                "classification": "standard",
            }
        else:
            db.add_custom_book(key, title, None, fmt_hint, "standard", [normalize(title)])
            book = {
                "key": key,
                "title": title,
                "lexile": 0,
                "format": fmt_hint,
                "classification": "standard",
            }
    ug_warning = None
    _rcfg = get_reader(reader)
    if _rcfg and _rcfg.get("warn_upper_grade") and book.get("interest_level") == "UG":
        ug_warning = (
            f"📚 **{book['title']}** is tagged for upper grades (9+). "
            f"Make sure a parent has previewed the content."
        )
    result = scoring.compute_points(book, reader, pages, audiobook=audiobook)
    ppp = result["ppp"]
    points = result["points"]
    today_local = _today()
    session_date_local = _parse_session_date(date_hint, today_local)
    if session_date_local is None:
        return _ephemeral(
            f"📅 Couldn't understand `date={date_hint}` (or it's in the future).\n"
            "Use `date=2026-06-07`, `date=yesterday`, or a day name like `date=saturday`.\n"
            "_Nothing was logged._"
        )
    is_backdated = session_date_local != today_local
    prev_combined = sum(db.get_total_stats(k)["pts"] for k in READER_KEYS)
    prev_total = db.get_total_stats(reader)["pts"]
    db.log_session(
        reader,
        book["key"],
        book["title"],
        pages,
        minutes,
        ppp,
        points,
        finished=finished,
        session_date=session_date_local.isoformat(),
        audiobook=audiobook,
    )
    daily = db.get_daily_stats(reader, session_date_local.isoformat())
    weekly = db.get_weekly_stats(reader, today=session_date_local)
    total = db.get_total_stats(reader)
    fmt = result["format"]
    if fmt in scoring.SPECIAL_OVERRIDES:
        score_line = (
            f"{pages} pages × {ppp} pts/pg "
            f"({fmt.replace('_', ' ')}) = **{fmt_pts(points)} pts**"
        )
    elif result.get("tier") == "override":
        score_line = f"{pages} pages × {ppp} pts/pg (override) = **{fmt_pts(points)} pts**"
    else:
        tier_label = scoring.TIER_LABELS.get(result["tier"], result["tier"])
        bonus_str = f" +{result['bonus']} classic bonus" if result.get("bonus") else ""
        density = result.get("density", 1.0)
        density_str = f" ×{density} density" if density != 1.0 else ""
        score_line = (
            f"{pages} pages × {ppp} pts/pg "
            f"({result['lexile']}L, {tier_label}{bonus_str}{density_str}) "
            f"= **{fmt_pts(points)} pts**"
        )
    if audiobook:
        full = result.get("full_ppp")
        score_line += f"  ·  🎧 _audiobook: ¼ points_ (was {full} pts/pg)"
    day_label = _fmt_today_label(session_date_local) if is_backdated else "Today"
    lines = [
        f"📖 **{reader.capitalize()} — {book['title']}**"
        + (" 🎧" if audiobook else "")
        + (" _(finished!)_" if finished else "")
        + (f" _(logged for {day_label})_" if is_backdated else ""),
        score_line,
        (
            f"{day_label}: {daily['pages']} pages · "
            f"Week: {fmt_pts(weekly['pts'])} pts · "
            f"Total: {fmt_pts(total['pts'])} pts"
        ),
    ]
    if ug_warning:
        lines.append(ug_warning)
    milestone_msgs = check_milestones(reader, prev_total, total["pts"])
    lines.extend(milestone_msgs)
    for msg in milestone_msgs:
        gcal.post_milestone(reader, msg, total["pts"], session_date_local)
    new_combined = sum(db.get_total_stats(k)["pts"] for k in READER_KEYS)
    for pct in check_family_goal(prev_combined, new_combined):
        fam_msg = f"🏆 **Family goal {pct}% reached: {fmt_pts(new_combined)} / {FAMILY_GOAL} pts!**"
        lines.append(fam_msg)
        gcal.post_family_goal(pct, new_combined, FAMILY_GOAL, session_date_local)
    bingo_lines = _process_bingo(
        reader,
        pages,
        minutes,
        book,
        finished,
        book["key"],
        session_date_local.isoformat(),
        audiobook=audiobook,
    )
    if bingo_lines:
        lines.append("")
        lines.extend(bingo_lines)
    _post_realtime_summaries(reader, today_local)
    # For backdated sessions, also update the session day's gcal event
    if is_backdated:
        _post_realtime_summaries(reader, session_date_local)
    return _in_channel("\n".join(lines))


# ===========================================================================

# /reading  — totals dashboard   (unchanged from live app)

# ===========================================================================


@app.post("/slash/reading")
async def slash_reading(request: Request):

    form = await request.form()
    if not _valid_slash_token(form, SLASH_TOKEN_READING):
        return _ephemeral("⛔ Unauthorized (invalid slash-command token).")
    text = (form.get("text") or "").strip().lower()
    if text == "export":
        csv = db.get_all_sessions_csv()
        return _ephemeral(f"```\n{csv}\n```")
    _rk = resolve_reader(text)
    if _rk:
        readers = [_rk]
    else:
        readers = list(READER_KEYS)
    today_local = _today()
    lines = []
    for reader in readers:
        daily = db.get_daily_stats(reader, today_local.isoformat())
        weekly = db.get_weekly_stats(reader, today=today_local)
        total = db.get_total_stats(reader)
        recent = db.get_recent_sessions(reader, limit=3)
        books_finished = _books_finished_count(reader)
        name = reader.capitalize()
        next_ms = next(((t, msg) for t, msg in MILESTONE_THRESHOLDS if total["pts"] < t), None)
        ms_str = f" · next milestone: {next_ms[0]} pts" if next_ms else " · 🏆 all milestones hit!"
        awarded = db.bingo_get_lines_awarded(reader)
        bingo_str = f" · 🎯 {len(awarded)} bingo line(s)" if awarded else ""
        lines.append(f"**{name}**")
        lines.append(f"Today: {daily['pages']} pages · {fmt_pts(daily['pts'])} pts")
        lines.append(f"This week: {fmt_pts(weekly['pts'])} pts · {weekly['pages']} pages")
        lines.append(
            f"All-time: **{fmt_pts(total['pts'])} pts** · "
            f"**{books_finished} books finished** · "
            f"{total['pages']} pages · {total['days_read']} days read"
            f"{ms_str}{bingo_str}"
        )
        if recent:
            lines.append("Recent:")
            for s in recent:
                lines.append(
                    f"  • {s['book_title']} — {s['pages']}p → {fmt_pts(s['points'])} pts ({s['session_date']})"
                )
        lines.append("")
    combined = sum(db.get_total_stats(k)["pts"] for k in READER_KEYS)
    pct = min(int(combined / FAMILY_GOAL * 100), 100)
    bar_filled = pct // 10
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    lines.append(f"Family goal: {bar} {pct}%  ({fmt_pts(combined)} / {FAMILY_GOAL} pts)")
    return _ephemeral("\n".join(lines).rstrip())


# ===========================================================================

# /book  — look up a title's pts/pg, or set its Lexile   (unchanged)

# ===========================================================================


@app.post("/slash/book")
async def slash_book(request: Request):

    form = await request.form()
    if not _valid_slash_token(form, SLASH_TOKEN_BOOK):
        return _ephemeral("⛔ Unauthorized (invalid slash-command token).")
    raw = (form.get("text") or "").strip()
    if not raw:
        return _ephemeral(
            "Usage:\n"
            '• `/book "title"` — look up pts/pg\n'
            '• `/book "title" lexile=750` — set/update the Lexile for an unknown or custom book'
        )
    lex_m = re.search(r"\blexile\s*=\s*(\d+)", raw, re.I)
    set_lexile = int(lex_m.group(1)) if lex_m else None
    query = re.sub(r"\blexile\s*=\s*\d+", "", raw, flags=re.I).strip().strip('"').strip("'").strip()
    if not query:
        return _ephemeral('Usage: `/book "title"` or `/book "title" lexile=750`')
    book, score = find_book(query)
    if set_lexile is not None:
        if book is not None and score < 90:
            book = None
        if book is not None:
            updated = db.update_custom_book_lexile(book["key"], set_lexile)
            if updated:
                book["lexile"] = set_lexile
                ppp = " · ".join(
                    f"{get_reader(k)['name']}: **{scoring.compute_points(book, k, 1)['ppp']} pts/pg**"
                    for k in READER_KEYS
                )
                return _ephemeral(f"✅ Updated **{book['title']}** → Lexile {set_lexile}L\n" + ppp)
            else:
                lex = book.get("lexile") or "N/A"
                return _ephemeral(
                    f"📚 **{book['title']}** is a built-in book (currently {lex}L) — "
                    f"its Lexile can't be changed here."
                )
        else:
            title = query.strip('"').strip("'")
            key = re.sub(r"\s+", "-", normalize(title))[:40]
            db.add_custom_book(
                key, title, set_lexile, "chapter_book", "standard", [normalize(title)]
            )
            book = {
                "key": key,
                "title": title,
                "lexile": set_lexile,
                "format": "chapter_book",
                "classification": "standard",
            }
            ppp = " · ".join(
                f"{get_reader(k)['name']}: **{scoring.compute_points(book, k, 1)['ppp']} pts/pg**"
                for k in READER_KEYS
            )
            return _ephemeral(
                f"✅ Added **{title}** as a chapter book at {set_lexile}L\n" + ppp + "\n"
                f'Log sessions with `/read [name] "{title}" pages=N`'
            )
    if book is None:
        return _ephemeral(
            f"❓ Couldn't find **{query}**.\n"
            "• Log a session with `format=chapter lexile=750` to add it\n"
            f'• Or: `/book "{query}" lexile=750`'
        )
    per_reader = [(get_reader(k), scoring.compute_points(book, k, 1)) for k in READER_KEYS]
    fmt = book.get("format", "chapter_book").replace("_", " ")
    cls = book.get("classification", "standard").replace("_", " ")
    lex = f"{book['lexile']}L" if book.get("lexile") else "N/A"
    il = book.get("interest_level", "")
    il_str = f" · AR: {il}" if il else ""
    dens = scoring.get_density(book)
    d_str = f" · density ×{dens}" if dens != 1.0 else ""
    reader_lines = [
        f"{rc['name']}: **{cp['ppp']} pts/pg** ({scoring.TIER_LABELS.get(cp['tier'], cp['tier'])})"
        for rc, cp in per_reader
    ]
    lines = [
        f"📚 **{book['title']}**",
        f"Format: {fmt} · Lexile: {lex} · {cls}{il_str}{d_str}",
        *reader_lines,
    ]
    if score < 90:
        lines.append(f'_(matched "{query}" with {score}% confidence)_')
    if not book.get("lexile"):
        lines.append(f"_(Lexile unknown — set it with `/book \"{book['title']}\" lexile=750`)_")
    if book.get("interest_level") == "UG":
        _warn = [rc["name"] for rc, _ in per_reader if rc.get("warn_upper_grade")]
        if _warn:
            lines.append(
                f"⚠️ _Upper grades (9+) — parent preview recommended for {' & '.join(_warn)}_"
            )
    return _ephemeral("\n".join(lines))


# ===========================================================================

# /bingo  — check/uncheck/show/audit   (unchanged from live app)

# ===========================================================================


@app.post("/slash/bingo")
async def slash_bingo(request: Request):

    form = await request.form()
    if not _valid_slash_token(form, SLASH_TOKEN_BINGO):
        return _ephemeral("⛔ Unauthorized (invalid slash-command token).")
    text = (form.get("text") or "").strip()
    if not text:
        return _ephemeral(
            "Usage:\n"
            "• `/bingo check alex pillow fort` — mark a square\n"
            "• `/bingo uncheck alex pillow fort` — undo a check\n"
            "• `/bingo show alex` — view current card\n"
            "• `/bingo audit alex` — show method + timestamp per square"
        )
    parts = text.split(None, 2)
    sub = parts[0].lower() if parts else ""
    if sub in ("check", "uncheck", "show", "audit"):
        if len(parts) < 2:
            return _ephemeral(f"Usage: `/bingo {sub} [{'|'.join(READER_KEYS)}] [square]`")
        reader = resolve_reader(parts[1])
        if not reader:
            return _ephemeral(
                f"Unknown reader **{parts[1]}**. Use one of: {', '.join(READER_KEYS)}."
            )
        square_query = parts[2] if len(parts) > 2 else ""
    else:
        return _ephemeral("Unknown subcommand. Use: `check`, `uncheck`, `show`, or `audit`.")
    if sub == "show":
        card_num = db.get_bingo_card_num(reader)
        squares = bingo_mod.get_card_squares(reader, card_num)
        checked = db.bingo_get_checked(reader)
        awarded = db.bingo_get_lines_awarded(reader)
        bpts = len(awarded) * bingo_mod.line_bonus(card_num)
        rows = []
        for i in range(0, 25, 5):
            row = []
            for sid, label in squares[i : i + 5]:
                mark = "✅" if sid in checked else "⬜"
                row.append(f"{mark} {label[:20]}")
            rows.append("  ".join(row))
        card_label = f" (Card {card_num})" if card_num > 1 else ""
        lines = [
            f"**{reader.capitalize()}'s Bingo Card{card_label}**",
            "```",
            *rows,
            "```",
            f"Lines completed: {len(awarded)}  ·  Bonus pts: {bpts}",
        ]
        return _ephemeral("\n".join(lines))
    if sub == "audit":
        card_num = db.get_bingo_card_num(reader)
        state = {r["square_id"]: r for r in db.bingo_get_state(reader)}
        squares = bingo_mod.get_card_squares(reader, card_num)
        card_label = f" (Card {card_num})" if card_num > 1 else ""
        lines = [f"**{reader.capitalize()} bingo audit{card_label}:**"]
        for sid, label in squares:
            s = state.get(sid)
            if s and s.get("checked"):
                ts = (s.get("checked_at") or "")[:16].replace("T", " ")
                method = s.get("method", "?")
                reason = s.get("reason") or ""
                lines.append(
                    f"  ✅ **{label}** — {method} @ {ts}" + (f"  _{reason}_" if reason else "")
                )
            else:
                lines.append(f"  ⬜ {label}")
        awarded = db.bingo_get_lines_awarded(reader)
        lines.append(f"\nLines awarded: {', '.join(sorted(awarded)) or 'none'}")
        return _ephemeral("\n".join(lines))
    if not square_query:
        return _ephemeral(f"Which square? `/bingo {sub} {reader} <square name or ID>`")
    _card_num = db.get_bingo_card_num(reader)
    match = bingo_mod.find_square(reader, square_query, card_num=_card_num)
    if match is None:
        return _ephemeral(
            f"❓ Couldn't match **{square_query}** to a square on {reader.capitalize()}'s card.\n"
            f"Try `/bingo show {reader}` to see all squares."
        )
    square_id, label = match
    if sub == "uncheck":
        ok = db.bingo_uncheck(reader, square_id)
        if ok:
            return _ephemeral(
                f"↩️ Unchecked **{label}** for {reader.capitalize()}. "
                f"(Any points already awarded are kept.)"
            )
        return _ephemeral(f"**{label}** wasn't checked — nothing to undo.")
    norm_q = square_query.lower().replace("_", " ").strip()
    if norm_q not in (square_id.lower().replace("_", " "), label.lower()):
        return _ephemeral(
            f"Did you mean **{label}** (`{square_id}`)?\n"
            f"If yes, run: `/bingo check {reader} {square_id.lower()}`"
        )
    ok = db.bingo_check(reader, square_id, "manual", "manual check")
    if not ok:
        return _ephemeral(f"**{label}** is already checked — nothing to do.")
    out_lines = [f"✅ Checked **{label}** for {reader.capitalize()}!"]
    _award_bingo_lines(reader, out_lines, card_num=db.get_bingo_card_num(reader))
    return _in_channel("\n".join(out_lines))


# ===========================================================================
# /alexa  — Alexa Custom Skill endpoint
# ===========================================================================


def _alexa_response(text: str, end_session: bool = True):
    return JSONResponse(
        {
            "version": "1.0",
            "response": {
                "outputSpeech": {"type": "PlainText", "text": text},
                "shouldEndSession": end_session,
            },
        }
    )


def _alexa_slot(slots: dict, name: str) -> str | None:
    slot = slots.get(name) or {}
    # Prefer resolved value for custom slot types
    for authority in (slot.get("resolutions") or {}).get("resolutionsPerAuthority", []):
        if (authority.get("status") or {}).get("code") == "ER_SUCCESS_MATCH":
            values = authority.get("values", [])
            if values:
                return values[0]["value"]["name"]
    return slot.get("value") or None


@app.post("/alexa")
async def alexa_skill(request: Request):
    # Alexa is opt-in: with no skill ID configured, the endpoint is disabled.
    if not ALEXA_SKILL_ID:
        return JSONResponse({"error": "alexa not configured"}, status_code=403)
    body = await request.json()
    app_id = (
        (body.get("context") or {}).get("System", {}).get("application", {}).get("applicationId")
    )
    if app_id != ALEXA_SKILL_ID:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    req = body.get("request", {})
    req_type = req.get("type", "")
    if req_type == "LaunchRequest":
        return _alexa_response(
            "Welcome to Reading Bot! Say something like: " "Alex read 30 pages of Dog Man.",
            end_session=False,
        )
    if req_type == "SessionEndedRequest":
        return JSONResponse({"version": "1.0", "response": {}})
    if req_type != "IntentRequest":
        return JSONResponse({"version": "1.0", "response": {}})
    intent = req.get("intent", {})
    intent_name = intent.get("name", "")
    if intent_name in ("AMAZON.CancelIntent", "AMAZON.StopIntent"):
        return _alexa_response("Goodbye!")
    if intent_name == "AMAZON.HelpIntent":
        return _alexa_response(
            "To log reading, say: Alex read 30 pages of Dog Man. "
            "You can also say 'finished' at the end if the book is done. "
            "Replace Alex with Sam for the other reader.",
            end_session=False,
        )
    if intent_name != "LogReadingIntent":
        return _alexa_response(
            "Sorry, I didn't understand that. Try saying: Alex read 30 pages of Dog Man."
        )
    slots = intent.get("slots", {})
    reader_raw = _alexa_slot(slots, "reader")
    book_raw = _alexa_slot(slots, "book")
    pages_raw = _alexa_slot(slots, "pages")
    mins_raw = _alexa_slot(slots, "minutes")
    fin_raw = _alexa_slot(slots, "finished")
    reader = resolve_reader(reader_raw)
    if not reader:
        return _alexa_response(
            "Sorry, I need to know who's reading. Say Alex or Sam.",
            end_session=False,
        )
    if not book_raw:
        return _alexa_response(
            f"What book did {reader.capitalize()} read?",
            end_session=False,
        )
    try:
        pages = int(pages_raw)
        if pages <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return _alexa_response(
            f"How many pages did {reader.capitalize()} read? Try saying a number.",
            end_session=False,
        )
    if pages > MAX_PAGES:
        return _alexa_response(
            f"That's more than {MAX_PAGES} pages — try logging it in smaller sessions.",
            end_session=False,
        )
    try:
        minutes = int(mins_raw) if mins_raw else 0
    except (TypeError, ValueError):
        minutes = 0
    finished = (fin_raw or "").lower() in ("yes", "true", "finished", "done")
    book, _ = find_book(book_raw)
    if book is None:
        key = re.sub(r"\s+", "-", normalize(book_raw))[:40]
        title = book_raw.strip()
        db.add_custom_book(key, title, None, "chapter_book", "standard", [normalize(title)])
        book = {
            "key": key,
            "title": title,
            "lexile": 0,
            "format": "chapter_book",
            "classification": "standard",
        }
    result = scoring.compute_points(book, reader, pages)
    ppp = result["ppp"]
    points = result["points"]
    today_local = _today()
    prev_total = db.get_total_stats(reader)["pts"]
    db.log_session(
        reader,
        book["key"],
        book["title"],
        pages,
        minutes,
        ppp,
        points,
        finished=finished,
        session_date=today_local.isoformat(),
    )
    total = db.get_total_stats(reader)["pts"]
    milestone_msgs = check_milestones(reader, prev_total, total)
    for msg in milestone_msgs:
        gcal.post_milestone(reader, msg, total, today_local)
    _process_bingo(reader, pages, minutes, book, finished, book["key"], today_local.isoformat())
    _post_realtime_summaries(reader, today_local)
    finish_phrase = " You finished the book!" if finished else ""
    milestone_phrase = f" {reader.capitalize()} hit a milestone!" if milestone_msgs else ""
    spoken = (
        f"Logged! {reader.capitalize()} read {pages} pages of {book['title']} "
        f"and earned {fmt_pts(points)} points.{finish_phrase}"
        f" Total is now {fmt_pts(total)} points.{milestone_phrase}"
    )
    return _alexa_response(spoken)
