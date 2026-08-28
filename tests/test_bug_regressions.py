"""Regressions for bugs found in the 2026-08 correctness review.

Every test here fails against the code as it stood before its fix. They are
grouped by defect rather than by module, so a change that reintroduces one names
the original problem in its failure message.
"""

import importlib
from datetime import date, timedelta
from pathlib import Path

import pytest

import app as app_module

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "regress.db"))
    import db as db_module

    importlib.reload(db_module)
    db_module.init_db()
    monkeypatch.setattr(app_module, "db", db_module)
    yield db_module
    importlib.reload(db_module)


def rows(db, **where):
    sql = "SELECT * FROM sessions"
    if where:
        sql += " WHERE " + " AND ".join("%s=?" % k for k in where)
    with db.get_conn() as c:
        return [dict(r) for r in c.execute(sql, tuple(where.values()))]


class TestBingoBonusDate:
    """Bonus rows were stamped with the container's UTC date.

    After early evening Eastern that is tomorrow, which stops the streak walk at
    the first row, hides the bonus from today's board, and on a Sunday credits it
    to next week.
    """

    def test_add_bingo_points_honours_an_explicit_local_date(self, db):
        db.add_bingo_points("alex", 25, "Bingo Row 1", session_date="2026-07-04")
        assert rows(db)[0]["session_date"] == "2026-07-04"

    def test_manual_web_check_awards_on_the_local_date(self, db, monkeypatch):
        """Drives the real endpoint: the call site is what omitted the date."""
        from fastapi.testclient import TestClient

        local = date(2026, 7, 4)
        monkeypatch.setattr(app_module, "_today", lambda: local)
        squares = app_module.bingo_mod.get_card_squares("alex", 1)
        for sq in squares[:4]:  # four of the top row; the endpoint checks the fifth
            db.bingo_check("alex", sq[0], "manual", "test")

        with TestClient(app_module.app) as client:
            r = client.post(
                "/api/bingo", json={"reader": "alex", "square_id": squares[4][0], "checked": True}
            )
            assert r.status_code == 200, r.text

        bonus = rows(db, book_key="bingo-bonus")
        assert bonus, "completing a row should award a bonus"
        assert (
            bonus[0]["session_date"] == local.isoformat()
        ), "bonus was dated %s, not the local date %s" % (
            bonus[0]["session_date"],
            local.isoformat(),
        )

    def test_bonus_is_tagged_with_the_current_season(self, db, monkeypatch):
        """The INSERT omitted `season`, so bonuses silently took the hardcoded
        schema default and were archived under the wrong year."""
        monkeypatch.setattr(db, "CURRENT_SEASON", "2027-summer")
        db.add_bingo_points("alex", 25, "Bingo Row 1", session_date="2027-07-04")
        assert rows(db)[0]["season"] == "2027-summer"


class TestWeeklyWindow:
    """ "This week" had no upper bound, so a backdated log spanned two weeks."""

    def test_backdating_reports_that_week_only(self, db):
        """/read ... date=<last week> calls get_weekly_stats(today=<that date>).
        Without an upper bound the answer ran from that Monday to forever."""
        backdated = date(2026, 7, 8)  # Wednesday of the earlier week
        current = date(2026, 7, 15)  # Wednesday of the following week
        db.log_session(
            "alex", "b1", "Backdated", 10, 0, 1.0, 10.0, session_date=backdated.isoformat()
        )
        db.log_session(
            "alex", "b2", "Later Week", 99, 0, 1.0, 99.0, session_date=current.isoformat()
        )
        assert db.get_weekly_stats("alex", today=backdated)["pts"] == 10.0

    def test_a_future_session_is_not_counted(self, db):
        today = date(2026, 7, 15)
        monday = today - timedelta(days=today.weekday())
        db.log_session("alex", "b1", "This Week", 10, 0, 1.0, 10.0, session_date=today.isoformat())
        db.log_session(
            "alex",
            "b2",
            "Next Week",
            50,
            0,
            1.0,
            50.0,
            session_date=(monday + timedelta(days=8)).isoformat(),
        )
        assert db.get_weekly_stats("alex", today=today)["pts"] == 10.0


class TestBingoPageMilestones:
    """Page milestones counted comic and audiobook pages they exclude by rule."""

    def test_comic_pages_do_not_count_toward_the_daily_milestone(self, db, monkeypatch):
        monkeypatch.setattr(
            app_module,
            "_book_by_key_index",
            lambda: {
                "dogman": {"key": "dogman", "format": "graphic_novel"},
                "novel": {"key": "novel", "format": "chapter_book"},
            },
        )
        db.log_session("alex", "dogman", "Dog Man", 49, 0, 0.2, 9.8, session_date="2026-07-04")
        db.log_session("alex", "novel", "A Novel", 1, 0, 1.0, 1.0, session_date="2026-07-04")
        # 49 + 1 reaches 50 by raw total, but only one page of it is prose.
        assert db.get_daily_stats("alex", "2026-07-04")["pages"] == 50
        assert app_module._prose_pages_for_day("alex", "2026-07-04") == 1

    def test_audiobook_pages_do_not_count_toward_the_daily_milestone(self, db, monkeypatch):
        monkeypatch.setattr(
            app_module,
            "_book_by_key_index",
            lambda: {"novel": {"key": "novel", "format": "chapter_book"}},
        )
        db.log_session(
            "alex", "novel", "A Novel", 99, 0, 1.0, 24.8, session_date="2026-07-04", audiobook=True
        )
        db.log_session("alex", "novel", "A Novel", 1, 0, 1.0, 1.0, session_date="2026-07-04")
        assert app_module._prose_pages_for_day("alex", "2026-07-04") == 1

    def test_an_unknown_book_is_assumed_to_be_prose(self, db, monkeypatch):
        monkeypatch.setattr(app_module, "_book_by_key_index", lambda: {})
        db.log_session(
            "alex", "mystery", "Not In Catalogue", 40, 0, 1.0, 40.0, session_date="2026-07-04"
        )
        assert app_module._prose_pages_for_day("alex", "2026-07-04") == 40

    def test_book_total_pages_can_exclude_listening(self, db):
        db.log_session(
            "alex", "novel", "A Novel", 80, 0, 1.0, 80.0, session_date="2026-07-01", audiobook=True
        )
        db.log_session("alex", "novel", "A Novel", 30, 0, 1.0, 30.0, session_date="2026-07-02")
        assert db.get_book_total_pages("alex", "novel") == 110
        assert db.get_book_total_pages("alex", "novel", exclude_audiobook=True) == 30

    def test_books_finished_can_exclude_listening(self, db):
        today = date(2026, 7, 15)
        db.log_session(
            "alex",
            "heard",
            "Heard It",
            10,
            0,
            1.0,
            2.5,
            finished=True,
            session_date=today.isoformat(),
            audiobook=True,
        )
        db.log_session(
            "alex",
            "read",
            "Read It",
            10,
            0,
            1.0,
            10.0,
            finished=True,
            session_date=today.isoformat(),
        )
        assert db.get_books_finished_this_week("alex", today=today) == 2
        assert db.get_books_finished_this_week("alex", today=today, exclude_audiobook=True) == 1


class TestParserLexile:
    """`lexile=750` was never stripped, so it ended up inside the stored title."""

    def test_lexile_is_extracted_and_removed_from_the_title(self):
        from parser import parse_read_command

        r = parse_read_command('alex "Brand New Book" pages=30 format=chapter lexile=750')
        assert r["book_raw"] == "Brand New Book"
        assert r["lexile"] == 750
        assert "lexile" not in r["book_raw"].lower()
        assert '"' not in r["book_raw"]

    def test_a_title_without_a_lexile_is_untouched(self):
        from parser import parse_read_command

        r = parse_read_command('alex "Dog Man" pages=40')
        assert r["book_raw"] == "Dog Man"
        assert r["lexile"] is None


class TestLogPageEscaping:
    """Book titles reach /log from the LAN and were written into innerHTML raw."""

    def test_every_interpolated_title_or_event_is_escaped(self):
        src = (ROOT / "board" / "log.html").read_text(encoding="utf-8")
        for raw in (
            "${b.title}",
            "${title}<button",
            "${d.book_title}",
            "${d.ug_warning}",
            "${e}</div>",
        ):
            assert raw not in src, "unescaped interpolation still present: %s" % raw

    def test_the_escape_helper_still_exists(self):
        src = (ROOT / "board" / "log.html").read_text(encoding="utf-8")
        assert "function esc(s)" in src


class TestApiLogValidation:
    """/api/log is reachable from the LAN and trusted its JSON."""

    def test_truthy_rejects_the_string_false(self):
        for value in (False, "false", "False", 0, None, "", "no"):
            assert app_module._truthy(value) is False, value

    def test_truthy_accepts_real_affirmatives(self):
        for value in (True, "true", "TRUE", "yes", 1, "on"):
            assert app_module._truthy(value) is True, value
