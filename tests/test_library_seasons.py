"""Season tagging, and the guarantee that the library never clears.

Points and bingo reset when a season rolls -- that is the competition. Books
read do not: the library is a permanent record, and each book carries the
season(s) it was read in.
"""

import importlib

import pytest

import app as app_module


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fresh database plus the app wired to it."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "seasons.db"))
    import db as db_module

    importlib.reload(db_module)
    db_module.init_db()
    monkeypatch.setattr(app_module, "db", db_module)
    return db_module


def log(
    db, reader="alex", key="hobbit", title="The Hobbit", pages=30, date="2026-07-01", finished=False
):
    db.log_session(
        reader, key, title, pages, 0, 1.0, float(pages), finished=finished, session_date=date
    )


class TestSeasonColumn:
    def test_exists_immediately_after_init_not_only_after_a_write(self, env):
        """The library has to query season before anyone logs anything."""
        with env.get_conn() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)")]
        assert "season" in cols

    def test_new_sessions_are_tagged_with_the_current_season(self, env, monkeypatch):
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-fall")
        log(env)
        with env.get_conn() as conn:
            assert [r[0] for r in conn.execute("SELECT season FROM sessions")] == ["2026-fall"]

    def test_legacy_rows_are_backfilled_with_legacy_season_not_current(self, tmp_path, monkeypatch):
        """Upgrading happens *into* a new season. Existing history belongs to the
        previous one, so backfilling with CURRENT_SEASON would relabel the whole
        back catalogue as read in a season it wasn't."""
        import sqlite3

        path = tmp_path / "legacy.db"
        # A database written by a version that predates the season column.
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,
               reader TEXT NOT NULL, book_key TEXT NOT NULL, book_title TEXT NOT NULL,
               pages INTEGER NOT NULL, minutes INTEGER NOT NULL, ppp REAL NOT NULL,
               points REAL NOT NULL, session_date TEXT NOT NULL, logged_at TEXT NOT NULL,
               finished INTEGER NOT NULL DEFAULT 0, audiobook INTEGER NOT NULL DEFAULT 0)""")
        conn.execute(
            "INSERT INTO sessions (reader,book_key,book_title,pages,minutes,ppp,points,"
            "session_date,logged_at) VALUES ('alex','hobbit','The Hobbit',30,0,1.0,30.0,"
            "'2026-07-01','2026-07-01T00:00:00')"
        )
        conn.commit()
        conn.close()

        monkeypatch.setenv("DB_PATH", str(path))
        monkeypatch.setenv("LEGACY_SEASON", "2026-summer")
        monkeypatch.setenv("CURRENT_SEASON", "2026-fall")
        import db as db_module

        importlib.reload(db_module)
        db_module.init_db()
        with db_module.get_conn() as c:
            assert [r[0] for r in c.execute("SELECT season FROM sessions")] == ["2026-summer"]
        importlib.reload(db_module)


class TestLibraryIsPermanent:
    def test_books_survive_a_season_roll(self, env, monkeypatch):
        """The behaviour the owner explicitly asked for: books read must not
        disappear when the competition resets."""
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-summer")
        log(env, key="hobbit", title="The Hobbit", date="2026-07-01", finished=True)
        summer = app_module._build_library_payload()
        summer_books = [b["title"] for b in summer["players"][0]["books"]]

        # Season rolls: new sessions land under a new tag.
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-fall")
        log(env, key="hatchet", title="Hatchet", date="2026-09-15")
        after = app_module._build_library_payload()
        after_books = [b["title"] for b in after["players"][0]["books"]]

        assert "The Hobbit" in after_books, "summer book vanished after the roll"
        assert "Hatchet" in after_books
        assert set(summer_books) <= set(after_books)

    def test_each_book_carries_the_seasons_it_was_read_in(self, env, monkeypatch):
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-summer")
        log(env, key="hobbit", date="2026-07-01")
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-fall")
        log(env, key="hatchet", title="Hatchet", date="2026-09-15")

        books = {b["key"]: b for b in app_module._build_library_payload()["players"][0]["books"]}
        assert books["hobbit"]["seasons"] == ["2026-summer"]
        assert books["hatchet"]["seasons"] == ["2026-fall"]

    def test_a_book_read_across_a_rollover_lists_both_seasons(self, env, monkeypatch):
        """Started in summer, finished in fall -- it belongs to both, so it is a
        list rather than an arbitrary single attribution."""
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-summer")
        log(env, key="hobbit", pages=30, date="2026-08-20")
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-fall")
        log(env, key="hobbit", pages=40, date="2026-09-05", finished=True)

        books = {b["key"]: b for b in app_module._build_library_payload()["players"][0]["books"]}
        assert books["hobbit"]["seasons"] == ["2026-fall", "2026-summer"]
        assert books["hobbit"]["pages_read"] == 70, "sessions across seasons must still sum"


class TestSeasonTotals:
    def test_per_season_totals_are_reported(self, env, monkeypatch):
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-summer")
        log(env, key="hobbit", pages=30, date="2026-07-01", finished=True)
        log(env, key="narnia", title="Narnia", pages=20, date="2026-07-02")
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-fall")
        log(env, key="hatchet", title="Hatchet", pages=50, date="2026-09-15")

        by_season = {
            s["season"]: s for s in app_module._build_library_payload()["players"][0]["by_season"]
        }
        assert by_season["2026-summer"]["pages"] == 50
        assert by_season["2026-summer"]["books_total"] == 2
        assert by_season["2026-summer"]["books_finished"] == 1
        assert by_season["2026-fall"]["pages"] == 50
        assert by_season["2026-fall"]["books_total"] == 1

    def test_payload_lists_every_season_and_the_current_one(self, env, monkeypatch):
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-summer")
        log(env, key="hobbit", date="2026-07-01")
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-fall")
        log(env, key="hatchet", title="Hatchet", date="2026-09-15")

        payload = app_module._build_library_payload()
        assert payload["seasons"] == ["2026-fall", "2026-summer"]
        assert payload["current_season"] == "2026-fall"

    def test_all_time_totals_still_span_every_season(self, env, monkeypatch):
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-summer")
        log(env, key="hobbit", pages=30, date="2026-07-01")
        monkeypatch.setattr(env, "CURRENT_SEASON", "2026-fall")
        log(env, key="hatchet", title="Hatchet", pages=50, date="2026-09-15")

        totals = app_module._build_library_payload()["players"][0]["totals"]
        assert totals["pages"] == 80
        assert totals["books_total"] == 2
