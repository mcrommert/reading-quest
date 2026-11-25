"""POST /api/log in position mode: the client reports the print page it is on and
reading-bot keeps one automatic row per reader/book/day in step with it."""

import importlib
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app as app_module

KEY = "sw-jedi-apprentice-the-fight-for-truth"
TODAY = date(2026, 11, 25)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pos.db"))
    import db as db_module

    importlib.reload(db_module)
    db_module.init_db()
    monkeypatch.setattr(app_module, "db", db_module)
    monkeypatch.setattr(app_module, "LOG_PIN", "")
    monkeypatch.setattr(app_module, "_today", lambda: TODAY)
    c = TestClient(app_module.app)
    c.db = db_module
    return c


def post(client, page, minutes=0, day=None, **extra):
    body = {"reader": "alex", "book_key": KEY, "page": page, "minutes": minutes,
            "source": "bookorbit"}
    if day:
        body["date"] = day
    body.update(extra)
    return client.post("/api/log", json=body)


def manual(client, pages, day=None, minutes=0):
    body = {"reader": "alex", "book_key": KEY, "pages": pages, "minutes": minutes}
    if day:
        body["date"] = day
    r = client.post("/api/log", json=body)
    assert r.status_code == 200
    return r


def rows(client, where="1=1"):
    with client.db.get_conn() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM sessions WHERE {where} ORDER BY id")]


def test_first_post_creates_row_with_page_minus_other(client):
    manual(client, 10)
    d = post(client, 68, 30).json()
    assert d["ok"] and d["logged"] and d["pages_added"] == 58
    assert d["row_pages"] == 58 and d["other_pages"] == 10 and d["page"] == 68
    auto = rows(client, "source='position'")
    assert len(auto) == 1 and auto[0]["pages"] == 58 and auto[0]["minutes"] == 30
    assert auto[0]["source_label"] == "bookorbit" and auto[0]["id"] == d["session_id"]


def test_second_post_updates_in_place(client):
    post(client, 20, 10)
    d = post(client, 35, 25).json()
    assert d["pages_added"] == 15 and d["row_pages"] == 35
    auto = rows(client, "source='position'")
    assert len(auto) == 1 and auto[0]["pages"] == 35 and auto[0]["minutes"] == 25
    assert auto[0]["points"] > 0


def test_identical_repost_is_noop_without_side_effects(client, monkeypatch):
    post(client, 30, 10)
    calls = []
    monkeypatch.setattr(app_module, "_process_bingo", lambda *a, **k: calls.append(1) or [])
    monkeypatch.setattr(app_module, "_post_realtime_summaries", lambda *a, **k: calls.append(1))
    d = post(client, 30, 10).json()
    assert d["ok"] and d["logged"] is False and d["pages_added"] == 0 and calls == []
    assert len(rows(client)) == 1


def test_backwards_position_keeps_pages_and_minutes_monotonic(client):
    post(client, 40, 30)
    d = post(client, 25, 12).json()
    assert d["logged"] is False and d["row_pages"] == 40
    r = rows(client)[0]
    assert r["pages"] == 40 and r["minutes"] == 30


def test_minutes_only_growth_updates_row_without_side_effects(client, monkeypatch):
    post(client, 40, 30)
    monkeypatch.setattr(app_module, "_process_bingo", lambda *a, **k: pytest.fail("fired"))
    d = post(client, 40, 45).json()
    assert d["logged"] and d["pages_added"] == 0 and d["events"] == []
    assert rows(client)[0]["minutes"] == 45


def test_next_day_counts_against_manual_and_position_rows(client):
    manual(client, 5, day="2026-11-23")
    post(client, 25, 10, day="2026-11-24")
    d = post(client, 40, 10).json()
    assert d["other_pages"] == 25 and d["row_pages"] == 15
    assert len(rows(client, "source='position'")) == 2


def test_manual_rows_are_counted_and_never_modified(client):
    manual(client, 12, minutes=7)
    before = rows(client, "source='manual'")
    post(client, 50, 20)
    post(client, 60, 25)
    assert rows(client, "source='manual'") == before


def test_page_below_logged_total_is_noop_without_row(client):
    manual(client, 50)
    d = post(client, 50, 10).json()
    assert d["logged"] is False and d["pages_added"] == 0 and d["row_pages"] == 0
    assert rows(client, "source='position'") == []
    assert post(client, 20, 10).json()["logged"] is False
    assert rows(client, "source='position'") == []


def test_finished_fires_once(client, monkeypatch):
    seen = []
    real = app_module._process_bingo

    def spy(*a, **k):
        seen.append(a[4])
        return real(*a, **k)

    monkeypatch.setattr(app_module, "_process_bingo", spy)
    post(client, 30, 10)
    d = post(client, 33, 12, finished=True).json()
    assert d["finished"] and seen == [False, True]
    d = post(client, 33, 12, finished=True).json()
    assert d["logged"] is False and len(seen) == 2
    d = post(client, 33, 12, finished=False).json()  # sticky
    assert d["finished"] is True and len(seen) == 2
    assert rows(client)[0]["finished"] == 1
    assert client.db.get_book_total_pages("alex", KEY) == 33


def test_finish_with_zero_pages_creates_row_once(client):
    d = post(client, 0, 0, finished=True).json()
    assert d["logged"] and d["row_pages"] == 0
    assert post(client, 0, 0, finished=True).json()["logged"] is False
    assert len(rows(client)) == 1


def test_milestone_fires_exactly_once_across_updates(client, monkeypatch):
    monkeypatch.setattr(app_module, "MILESTONE_THRESHOLDS", [(30.0, "Big **30**")])
    hits = []
    monkeypatch.setattr(app_module.gcal, "post_milestone", lambda *a, **k: hits.append(a))
    events = []
    for page in (5, 15, 60, 70, 70, 50, 90):
        events += post(client, page, page).json()["events"]
    assert len(hits) == 1
    assert events.count("Big 30") == 1


def test_bingo_squares_award_once_across_updates(client):
    first = post(client, 30, 40).json()  # 30 pages in one sitting
    assert [e for e in first["events"] if "Bingo" in e]
    checked = client.db.bingo_get_checked("alex")
    pts = client.db.get_total_stats("alex")["pts"]
    later = []
    for page in (31, 31, 32, 20):
        later += post(client, page, 40).json()["events"]
    assert client.db.bingo_get_checked("alex") == checked
    assert not any("auto-check" in e for e in later)
    assert client.db.get_total_stats("alex")["pts"] > pts  # only the 2 extra pages


def test_points_recomputed_from_scratch(client):
    import scoring

    post(client, 10)
    post(client, 25)
    r = rows(client)[0]
    exp = scoring.compute_points(app_module._book_by_key(KEY), "alex", 25)
    assert r["pages"] == 25 and r["ppp"] == exp["ppp"]
    assert r["points"] == pytest.approx(exp["points"])
    assert len(rows(client)) == 1


def test_wrong_pin_403(client, monkeypatch):
    monkeypatch.setattr(app_module, "LOG_PIN", "1234")
    assert post(client, 10).status_code == 403
    ok = client.post("/api/log", headers={"X-Log-Pin": "1234"},
                     json={"reader": "alex", "book_key": KEY, "page": 10})
    assert ok.status_code == 200


def test_validation_errors(client):
    assert client.post("/api/log", json={"reader": "alex", "page": 10}).status_code == 400
    assert post(client, 10, book_key="nope").status_code == 400
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    assert post(client, 10, day=tomorrow).status_code == 400
    assert post(client, -1).status_code == 400
    assert post(client, 5001).status_code == 400
    assert post(client, "x").status_code == 400
    assert post(client, 10, minutes=-3).status_code == 400
    assert post(client, 10, reader="nobody").status_code == 400
    assert rows(client) == []


def test_growth_per_post_capped(client):
    assert post(client, 3000).status_code == 400
    assert rows(client) == []
    assert post(client, 1500).status_code == 200


def test_migration_adds_columns_to_old_db(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, reader TEXT NOT NULL,
        book_key TEXT NOT NULL, book_title TEXT NOT NULL, pages INTEGER NOT NULL,
        minutes INTEGER NOT NULL, ppp REAL NOT NULL, points REAL NOT NULL,
        session_date TEXT NOT NULL, logged_at TEXT NOT NULL)"""
    )
    conn.execute("INSERT INTO sessions VALUES (1,'alex','b','B',5,5,1,5,'2026-07-01','x')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("DB_PATH", str(path))
    import db as db_module

    importlib.reload(db_module)
    db_module.init_db()
    db_module.init_db()  # idempotent
    with db_module.get_conn() as c:
        row = c.execute("SELECT source, source_label FROM sessions").fetchone()
        assert (row[0], row[1]) == ("manual", None)
        idx = [r[1] for r in c.execute("PRAGMA index_list(sessions)")]
    assert "ux_sessions_position_day" in idx
    out = db_module.upsert_position_row(
        "alex", "b", "B", 9, 3, "2026-07-02", False, False, lambda p: (1.0, float(p))
    )
    assert out["other_pages"] == 5 and out["row_pages"] == 4


def test_unique_index_blocks_second_position_row(client):
    post(client, 10)
    with pytest.raises(sqlite3.IntegrityError):
        with client.db.get_conn() as c:
            c.execute(
                "INSERT INTO sessions (reader,book_key,book_title,pages,minutes,ppp,points,"
                "session_date,logged_at,source) VALUES ('alex',?,'t',1,1,1,1,?,'x','position')",
                (KEY, TODAY.isoformat()),
            )
