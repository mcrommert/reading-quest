"""Persistence behaviour: the dedup guard and the lazy season migration.

db.py reads DB_PATH at import time, so each test points it at a temp file and
reloads the module rather than touching a real database.
"""

import importlib

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import db as db_module

    importlib.reload(db_module)
    db_module.init_db()
    yield db_module
    importlib.reload(db_module)


def _log(db, **over):
    kwargs = dict(
        reader="alex",
        book_key="some-book",
        book_title="Some Book",
        pages=30,
        minutes=0,
        ppp=1.0,
        points=30.0,
        finished=False,
        session_date="2026-07-01",
        audiobook=False,
    )
    kwargs.update(over)
    return db.log_session(**kwargs)


def _count(db):
    with db.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


def test_identical_session_within_the_window_is_dropped(db):
    """Double-submits (slash command retried, /log clicked twice) must not
    double-score. The guard is 90 seconds on the full session identity."""
    _log(db)
    _log(db)
    assert _count(db) == 1


def test_a_different_page_count_is_a_real_second_session(db):
    """Reading the same book twice in a day is legitimate and must be kept."""
    _log(db, pages=30)
    _log(db, pages=45)
    assert _count(db) == 2


def test_dedup_distinguishes_audiobook_from_reading(db):
    """Same book, same pages, different medium — different score, so not a dupe."""
    _log(db, audiobook=False)
    _log(db, audiobook=True)
    assert _count(db) == 2


def test_dedup_distinguishes_finishing_the_book(db):
    _log(db, finished=False)
    _log(db, finished=True)
    assert _count(db) == 2


def test_dedup_is_scoped_per_reader(db):
    """Two children reading the same book on the same day is the normal case."""
    _log(db, reader="alex")
    _log(db, reader="sam")
    assert _count(db) == 2


def test_backdated_sessions_are_separate(db):
    _log(db, session_date="2026-07-01")
    _log(db, session_date="2026-06-30")
    assert _count(db) == 2


def test_season_column_is_added_and_backfilled(db):
    """The season column arrives via ALTER TABLE inside log_session, not the
    schema — so a database created before it still gains it on first write."""
    _log(db)
    with db.get_conn() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)")]
        assert "season" in cols
        seasons = [r[0] for r in conn.execute("SELECT season FROM sessions")]
    assert seasons == [db.CURRENT_SEASON]


def test_advancing_a_card_clears_state_and_lines_together(db):
    """Line IDs are `line_N` on every card, not card-scoped — so they only stay
    unambiguous because advancing wipes bingo_state AND bingo_lines_awarded in
    the same step. If that ever becomes an archive instead of a delete, card 2
    starts life with card 1's lines already awarded."""
    db.bingo_check("alex", "W_OUTSIDE", "manual", "test")
    db.bingo_award_line("alex", "line_0")
    assert db.bingo_get_checked("alex") == {"W_OUTSIDE"}
    assert db.bingo_get_lines_awarded("alex") == {"line_0"}

    new_card = db.increment_bingo_card("alex")

    assert new_card == 2
    assert db.bingo_get_checked("alex") == set()
    assert db.bingo_get_lines_awarded("alex") == set()
    assert db.get_bingo_card_num("alex") == 2
