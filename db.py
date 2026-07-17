"""SQLite persistence layer."""

import sqlite3, os, json

from datetime import date, datetime, timedelta

DB_PATH = os.environ.get("DB_PATH", "/data/reading.db")

# Current reading season. Every new session is tagged with this so years can
# roll over cleanly (archive/compare across summers). Existing rows backfill to
# the default via the ADD COLUMN default below.
CURRENT_SEASON = os.environ.get("CURRENT_SEASON", "2026-summer")


SCHEMA = """

CREATE TABLE IF NOT EXISTS bingo_state (

    reader     TEXT    NOT NULL,

    square_id  TEXT    NOT NULL,

    checked    INTEGER NOT NULL DEFAULT 0,

    method     TEXT,               -- 'manual', 'auto', 'freebie'

    reason     TEXT,               -- human-readable trigger note

    checked_at TEXT,               -- ISO timestamp

    PRIMARY KEY (reader, square_id)

);



CREATE TABLE IF NOT EXISTS bingo_lines_awarded (

    reader     TEXT    NOT NULL,

    line_id    TEXT    NOT NULL,

    awarded_at TEXT    NOT NULL,

    PRIMARY KEY (reader, line_id)

);



CREATE TABLE IF NOT EXISTS summary_log (

    id         INTEGER PRIMARY KEY AUTOINCREMENT,

    event_type TEXT    NOT NULL,           -- 'daily', 'weekly', 'milestone'

    reader     TEXT    NOT NULL DEFAULT '',-- '' for family/weekly events

    event_date TEXT    NOT NULL,           -- YYYY-MM-DD

    posted_at  TEXT    NOT NULL,

    UNIQUE(event_type, reader, event_date)

);



CREATE TABLE IF NOT EXISTS sessions (

    id           INTEGER PRIMARY KEY AUTOINCREMENT,

    reader       TEXT    NOT NULL,

    book_key     TEXT    NOT NULL,

    book_title   TEXT    NOT NULL,

    pages        INTEGER NOT NULL,

    minutes      INTEGER NOT NULL,

    ppp          REAL    NOT NULL,

    points       REAL    NOT NULL,

    session_date TEXT    NOT NULL,

    logged_at    TEXT    NOT NULL,
    finished     INTEGER NOT NULL DEFAULT 0,
    audiobook    INTEGER NOT NULL DEFAULT 0,
    season       TEXT    NOT NULL DEFAULT '2026-summer'

);



CREATE TABLE IF NOT EXISTS books_custom (

    key            TEXT PRIMARY KEY,

    title          TEXT NOT NULL,

    lexile         INTEGER,

    format         TEXT NOT NULL DEFAULT 'chapter_book',

    classification TEXT NOT NULL DEFAULT 'standard',

    aliases        TEXT DEFAULT '[]',

    added_at       TEXT NOT NULL

);



CREATE TABLE IF NOT EXISTS gcal_events (

    event_type  TEXT NOT NULL,   -- 'daily', 'weekly'

    reader      TEXT NOT NULL DEFAULT '',

    event_date  TEXT NOT NULL,   -- YYYY-MM-DD

    gcal_id     TEXT NOT NULL,

    PRIMARY KEY (event_type, reader, event_date)

);



CREATE TABLE IF NOT EXISTS bingo_card_num (

    reader   TEXT PRIMARY KEY,

    card_num INTEGER NOT NULL DEFAULT 1

);

"""


def get_conn():

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def log_session(
    reader,
    book_key,
    book_title,
    pages,
    minutes,
    ppp,
    points,
    finished=False,
    session_date: str = None,
    audiobook=False,
):
    today = session_date or date.today().isoformat()
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        # Add columns if they don't exist yet (migration)
        for _col in (
            "finished INTEGER NOT NULL DEFAULT 0",
            "audiobook INTEGER NOT NULL DEFAULT 0",
            "season TEXT NOT NULL DEFAULT '2026-summer'",
        ):
            try:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {_col}")
            except Exception:
                pass
        # Dedup guard: skip if an identical session was logged within the last 90 seconds
        cutoff = (datetime.utcnow() - timedelta(seconds=90)).isoformat()
        existing = conn.execute(
            """SELECT 1 FROM sessions
               WHERE reader=? AND book_key=? AND pages=? AND session_date=? AND finished=?
               AND audiobook=? AND logged_at >= ?""",
            (reader, book_key, pages, today, 1 if finished else 0, 1 if audiobook else 0, cutoff),
        ).fetchone()
        if existing:
            return  # duplicate within 90s window — silently ignore
        conn.execute(
            """INSERT INTO sessions

               (reader,book_key,book_title,pages,minutes,ppp,points,session_date,logged_at,finished,audiobook,season)

               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                reader,
                book_key,
                book_title,
                pages,
                minutes,
                ppp,
                points,
                today,
                now,
                1 if finished else 0,
                1 if audiobook else 0,
                CURRENT_SEASON,
            ),
        )


def get_daily_stats(reader, day=None):

    if day is None:
        day = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(points),0) AS pts,

                      COALESCE(SUM(minutes),0) AS mins,

                      COALESCE(SUM(pages),0)   AS pages,

                      COUNT(*)                 AS sessions

               FROM sessions WHERE reader=? AND session_date=?""",
            (reader, day),
        ).fetchone()
    return dict(row)


def get_weekly_stats(reader, today: date = None):

    today = today or date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(points),0) AS pts,

                      COALESCE(SUM(minutes),0) AS mins,

                      COALESCE(SUM(pages),0)   AS pages

               FROM sessions WHERE reader=? AND session_date >= ?""",
            (reader, week_start),
        ).fetchone()
    return dict(row)


def get_total_stats(reader, since=None):

    with get_conn() as conn:
        if since:
            row = conn.execute(
                """SELECT COALESCE(SUM(points),0)          AS pts,

                          COALESCE(SUM(minutes),0)          AS mins,

                          COALESCE(SUM(pages),0)            AS pages,

                          COUNT(DISTINCT session_date)       AS days_read

                   FROM sessions WHERE reader=? AND session_date >= ?""",
                (reader, since),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT COALESCE(SUM(points),0)          AS pts,

                          COALESCE(SUM(minutes),0)          AS mins,

                          COALESCE(SUM(pages),0)            AS pages,

                          COUNT(DISTINCT session_date)       AS days_read

                   FROM sessions WHERE reader=?""",
                (reader,),
            ).fetchone()
    return dict(row)


def get_recent_sessions(reader, limit=5):

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT book_title, pages, minutes, points, session_date

               FROM sessions WHERE reader=?

               ORDER BY logged_at DESC LIMIT ?""",
            (reader, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_sessions_csv():

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT reader, book_title, pages, minutes, ppp, points, session_date "
            "FROM sessions ORDER BY logged_at"
        ).fetchall()
    lines = ["reader,book_title,pages,minutes,pts_per_page,points,date"]
    for r in rows:
        title = r["book_title"].replace(",", ";")
        lines.append(
            f"{r['reader']},{title},{r['pages']},{r['minutes']},"
            f"{r['ppp']},{r['points']},{r['session_date']}"
        )
    return "\n".join(lines)


def add_custom_book(key, title, lexile, fmt, classification, aliases):

    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO books_custom

               (key,title,lexile,format,classification,aliases,added_at)

               VALUES (?,?,?,?,?,?,?)""",
            (key, title, lexile, fmt, classification, json.dumps(aliases), now),
        )


def get_custom_books():

    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM books_custom").fetchall()
    books = []
    for r in rows:
        b = dict(r)
        b["aliases"] = json.loads(b["aliases"])
        books.append(b)
    return books


def get_streak(reader: str, since: str = None, today: date = None) -> int:
    """Count consecutive days with at least one session, ending today."""
    today = today or date.today()
    with get_conn() as conn:
        if since:
            rows = conn.execute(
                "SELECT DISTINCT session_date FROM sessions "
                "WHERE reader=? AND session_date >= ? ORDER BY session_date DESC",
                (reader, since),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT session_date FROM sessions "
                "WHERE reader=? ORDER BY session_date DESC",
                (reader,),
            ).fetchall()
    if not rows:
        return 0
    streak = 0
    check = today
    for row in rows:
        d = date.fromisoformat(row["session_date"])
        if d == check:
            streak += 1
            check = check - timedelta(days=1)
        else:
            break
    return streak


def has_summary_sent(event_type: str, reader: str, event_date: str) -> bool:

    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM summary_log WHERE event_type=? AND reader=? AND event_date=?",
            (event_type, reader, event_date),
        ).fetchone()
    return row is not None


def mark_summary_sent(event_type: str, reader: str, event_date: str):

    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO summary_log (event_type, reader, event_date, posted_at) "
                "VALUES (?,?,?,?)",
                (event_type, reader, event_date, now),
            )
        except Exception:
            pass  # UNIQUE constraint hit â€” already logged, safe to ignore


# â”€â”€ Bingo â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def bingo_init(reader: str, free_ids: set):
    """Ensure free squares are pre-checked; call once at startup / first use."""
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        for fid in free_ids:
            conn.execute(
                """INSERT OR IGNORE INTO bingo_state

                   (reader,square_id,checked,method,reason,checked_at)

                   VALUES (?,?,1,'freebie','FREE SPACE',?)""",
                (reader, fid, now),
            )


def bingo_get_checked(reader: str) -> set[str]:

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT square_id FROM bingo_state WHERE reader=? AND checked=1", (reader,)
        ).fetchall()
    return {r["square_id"] for r in rows}


def bingo_get_state(reader: str) -> list[dict]:
    """All squares for a reader with their full state."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM bingo_state WHERE reader=?", (reader,)).fetchall()
    return [dict(r) for r in rows]


def bingo_check(reader: str, square_id: str, method: str, reason: str = "") -> bool:
    """Mark a square checked. Returns False if already checked."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT checked FROM bingo_state WHERE reader=? AND square_id=?",
            (reader, square_id),
        ).fetchone()
        if existing and existing["checked"]:
            return False
        now = datetime.utcnow().isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO bingo_state

               (reader,square_id,checked,method,reason,checked_at)

               VALUES (?,?,1,?,?,?)""",
            (reader, square_id, method, reason, now),
        )
    return True


def bingo_uncheck(reader: str, square_id: str) -> bool:
    """Uncheck a square (parent override). Does not claw back points."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE bingo_state SET checked=0 WHERE reader=? AND square_id=?",
            (reader, square_id),
        )
    return cur.rowcount > 0


def bingo_get_lines_awarded(reader: str) -> set[str]:

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT line_id FROM bingo_lines_awarded WHERE reader=?", (reader,)
        ).fetchall()
    return {r["line_id"] for r in rows}


def bingo_award_line(reader: str, line_id: str):

    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO bingo_lines_awarded (reader,line_id,awarded_at) VALUES (?,?,?)",
            (reader, line_id, now),
        )


def get_books_finished_this_week(reader: str, today: date = None) -> int:
    """Count distinct book_keys with finished=1 in the last 7 days."""
    today = today or date.today()
    week_ago = (today - timedelta(days=6)).isoformat()
    with get_conn() as conn:
        try:
            row = conn.execute(
                """SELECT COUNT(DISTINCT book_key) AS cnt FROM sessions

                   WHERE reader=? AND finished=1 AND session_date>=?""",
                (reader, week_ago),
            ).fetchone()
            return row["cnt"] if row else 0
        except Exception:
            return 0


def get_book_first_session_date(reader: str, book_key: str) -> str | None:
    """Date of first session logged for this book by this reader."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MIN(session_date) AS d FROM sessions WHERE reader=? AND book_key=?",
            (reader, book_key),
        ).fetchone()
    return row["d"] if row else None


def add_bingo_points(reader: str, points: float, reason: str, session_date: str = None):
    """Log a synthetic session for bingo line bonus points."""
    today = session_date or date.today().isoformat()
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sessions

               (reader,book_key,book_title,pages,minutes,ppp,points,session_date,logged_at,finished)

               VALUES (?,?,?,?,?,?,?,?,?,0)""",
            (reader, "bingo-bonus", reason, 0, 0, 0.0, points, today, now),
        )


def update_custom_book_lexile(key: str, lexile: int) -> bool:
    """Update the Lexile of an existing custom book. Returns True if a row was updated."""
    with get_conn() as conn:
        cur = conn.execute("UPDATE books_custom SET lexile=? WHERE key=?", (lexile, key))
        return cur.rowcount > 0


def get_gcal_event_id(event_type: str, reader: str, event_date: str) -> str | None:

    with get_conn() as conn:
        row = conn.execute(
            "SELECT gcal_id FROM gcal_events WHERE event_type=? AND reader=? AND event_date=?",
            (event_type, reader, event_date),
        ).fetchone()
    return row["gcal_id"] if row else None


def set_gcal_event_id(event_type: str, reader: str, event_date: str, gcal_id: str):

    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO gcal_events (event_type, reader, event_date, gcal_id) "
            "VALUES (?,?,?,?)",
            (event_type, reader, event_date, gcal_id),
        )


def get_book_total_pages(reader: str, book_key: str) -> int:
    """Total pages logged for this book by this reader across all sessions."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(pages), 0) AS p FROM sessions WHERE reader=? AND book_key=?",
            (reader, book_key),
        ).fetchone()
    return int(row["p"]) if row else 0


# ── Bingo card number tracking ────────────────────────────────────────────────


def get_bingo_card_num(reader: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT card_num FROM bingo_card_num WHERE reader=?", (reader,)
        ).fetchone()
    return int(row["card_num"]) if row else 1


def increment_bingo_card(reader: str) -> int:
    """Advance reader to the next card and reset all bingo state. Returns new card_num."""
    with get_conn() as conn:
        current = conn.execute(
            "SELECT card_num FROM bingo_card_num WHERE reader=?", (reader,)
        ).fetchone()
        new_num = (int(current["card_num"]) + 1) if current else 2
        conn.execute(
            "INSERT OR REPLACE INTO bingo_card_num (reader, card_num) VALUES (?, ?)",
            (reader, new_num),
        )
        # Reset bingo squares and lines for new card
        conn.execute("DELETE FROM bingo_state WHERE reader=?", (reader,))
        conn.execute("DELETE FROM bingo_lines_awarded WHERE reader=?", (reader,))
    return new_num
