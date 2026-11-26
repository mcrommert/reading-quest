"""Typed "I'm on page N" entries: the parser forms, /read, the command bar and the
web form, all sharing the scrobbler's per-day position row."""

import importlib
from datetime import date

import pytest
from fastapi.testclient import TestClient

import app as app_module
from parser import parse_read_command

KEY = "sw-jedi-apprentice-the-fight-for-truth"
TITLE_Q = "The Fight for Truth"
TODAY = date(2026, 11, 25)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "pos.db"))
    import db as db_module

    importlib.reload(db_module)
    db_module.init_db()
    monkeypatch.setattr(app_module, "db", db_module)
    monkeypatch.setattr(app_module, "LOG_PIN", "")
    monkeypatch.setattr(app_module, "SLASH_TOKEN_READ", "")
    monkeypatch.setattr(app_module, "_today", lambda: TODAY)
    c = TestClient(app_module.app)
    c.db = db_module
    return c


def rows(client, where="1=1"):
    with client.db.get_conn() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM sessions WHERE {where} ORDER BY id")]


def slash(client, text):
    r = client.post("/slash/read", data={"text": text})
    assert r.status_code == 200
    return r.json()["text"]


def cmd(client, command):
    return client.post("/api/log", json={"command": command})


def scrobble(client, page, minutes=0, **extra):
    body = {"reader": "alex", "book_key": KEY, "page": page, "minutes": minutes,
            "source": "bookorbit"}
    body.update(extra)
    return client.post("/api/log", json=body).json()


def manual_pages(client, pages, day=None):
    body = {"reader": "alex", "book_key": KEY, "pages": pages}
    if day:
        body["date"] = day
    assert client.post("/api/log", json=body).status_code == 200


# ---------------------------------------------------------------- parser


@pytest.mark.parametrize(
    "tail",
    ["on page 85", "ON PAGE 85", "on pg 85", "on p 85", "on p. 85", "at page 85",
     "at=85", "on=85", "on  page   85", "on pages 85"],
)
def test_parser_position_forms(tail):
    r = parse_read_command(f'alex "Some Book" {tail} min=20')
    assert "error" not in r, r
    assert r["position"] == 85 and r["pages"] == 0 and r["minutes"] == 20
    assert r["book_raw"] == "Some Book"


def test_parser_position_leaves_title_alone():
    r = parse_read_command('alex "Mouse on the Mayflower" on page 40')
    assert (r["book_raw"], r["position"]) == ("Mouse on the Mayflower", 40)
    r = parse_read_command("alex Night at the Museum at=12")
    assert (r["book_raw"], r["position"]) == ("Night at the Museum", 12)
    r = parse_read_command("alex Mouse on the Mayflower 30 pages")
    assert (r["book_raw"], r["pages"], r["position"]) == ("Mouse on the Mayflower", 30, None)


def test_parser_page_equals_is_still_pages_read():
    for t in ("page=85", "p=85", "pages=85", "85p", "85 pages"):
        r = parse_read_command(f"alex book {t}")
        assert r["pages"] == 85 and r["position"] is None, t


def test_parser_position_with_flags_and_date():
    r = parse_read_command("alex book at page 85 audio finished date=yesterday")
    assert r["position"] == 85 and r["audiobook"] and r["finished"] and r["date"] == "yesterday"
    assert r["book_raw"] == "book"


def test_parser_position_and_pages_conflict():
    r = parse_read_command("alex book on page 85 pages=3")
    assert "error" in r and "not both" in r["error"]
    assert "error" in parse_read_command("alex book at=85 30 pages")


def test_parser_position_range():
    assert parse_read_command("alex book on page 0")["position"] == 0
    assert parse_read_command("alex book on page 5000")["position"] == 5000
    assert "error" in parse_read_command("alex book on page 5001")
    assert "error" in parse_read_command("alex book at=99999")


def test_parser_usage_mentions_both_forms():
    msg = parse_read_command("alex")["error"]
    assert "pages=" in msg and "on page" in msg


# ---------------------------------------------------------------- slash /read


def test_slash_position_creates_day_row(client):
    out = slash(client, f'alex "{TITLE_Q}" on page 68 min=30')
    assert "+68 pages (now on page 68)" in out and "pts" in out
    r = rows(client)
    assert len(r) == 1 and r[0]["source"] == "position" and r[0]["source_label"] == "mattermost"
    assert (r[0]["pages"], r[0]["minutes"], r[0]["book_key"]) == (68, 30, KEY)


def test_slash_second_post_updates_same_row_and_minutes_add(client):
    slash(client, f'alex "{TITLE_Q}" on page 20 min=10')
    out = slash(client, f'alex "{TITLE_Q}" at=37 min=20')
    assert "+17 pages (now on page 37)" in out
    r = rows(client)
    assert len(r) == 1 and (r[0]["pages"], r[0]["minutes"]) == (37, 30)


def test_slash_reconciles_with_scrobbler_and_manual_rows(client):
    manual_pages(client, 12)
    before = rows(client, "source='manual'")
    scrobble(client, 40, 25)  # row = 28
    out = slash(client, f'alex "{TITLE_Q}" on page 50 min=5')
    assert "+10 pages (now on page 50)" in out
    auto = rows(client, "source='position'")
    assert len(auto) == 1 and auto[0]["pages"] == 38 and auto[0]["minutes"] == 30
    assert auto[0]["source_label"] == "mattermost"
    assert rows(client, "source='manual'") == before
    # and the scrobbler then lands on the same row, max semantics for minutes
    d = scrobble(client, 55, 10)
    assert d["pages_added"] == 5 and d["row_pages"] == 43
    auto = rows(client, "source='position'")
    assert len(auto) == 1 and auto[0]["minutes"] == 30 and auto[0]["source_label"] == "bookorbit"


def test_slash_noop_reply_and_no_side_effects(client, monkeypatch):
    scrobble(client, 68, 10)
    pts = client.db.get_total_stats("alex")["pts"]
    monkeypatch.setattr(app_module, "_process_bingo", lambda *a, **k: pytest.fail("fired"))
    monkeypatch.setattr(app_module, "_post_realtime_summaries", lambda *a, **k: pytest.fail("fired"))
    out = slash(client, f'alex "{TITLE_Q}" on page 60')
    assert out.startswith("Already logged 68 pages of ") and "page 60 adds nothing." in out
    assert client.db.get_total_stats("alex")["pts"] == pts
    assert len(rows(client)) == 1 and rows(client)[0]["pages"] == 68


def test_slash_noop_with_minutes_still_adds_minutes(client):
    scrobble(client, 68, 10)
    out = slash(client, f'alex "{TITLE_Q}" on page 60 min=15')
    assert "adds nothing" in out and "15 minutes" in out
    assert rows(client)[0]["minutes"] == 25 and rows(client)[0]["pages"] == 68


def test_slash_unknown_book_echoes_position_syntax(client):
    out = slash(client, 'alex "Zzyzx Quuxbert Saga" on page 85')
    assert "on page 85 format=chapter lexile=750" in out and "pages=" not in out
    assert rows(client) == []
    out = slash(client, 'alex "Zzyzx Quuxbert Saga" on page 85 format=chapter')
    assert "on page 85 format=chapter lexile=750" in out and "pages=" not in out
    # pages syntax still echoes pages=
    out = slash(client, 'alex "Zzyzx Quuxbert Saga" pages=12')
    assert "pages=12 format=chapter" in out


def test_slash_unknown_book_with_format_then_logs(client):
    out = slash(client, 'alex "Zzyzx Quuxbert Saga" on page 30 format=early')
    assert "+30 pages (now on page 30)" in out
    r = rows(client)
    assert len(r) == 1 and r[0]["source"] == "position" and r[0]["pages"] == 30


def test_slash_backdated_position_and_finished(client):
    out = slash(client, f'alex "{TITLE_Q}" on page 20 date=2026-11-20 finished')
    assert "finished" in out and "logged for" in out
    r = rows(client)
    assert r[0]["session_date"] == "2026-11-20" and r[0]["finished"] == 1


def test_slash_audiobook_rows_counted_separately(client):
    manual_pages(client, 30)
    slash(client, f'alex "{TITLE_Q}" on page 40 audiobook')
    r = rows(client, "source='position'")
    assert len(r) == 1 and r[0]["pages"] == 40 and r[0]["audiobook"] == 1


def test_slash_pages_syntax_unchanged(client):
    out = slash(client, f'alex "{TITLE_Q}" pages=25 min=10')
    assert "25 pages" in out
    r = rows(client)
    assert len(r) == 1 and r[0]["source"] == "manual" and r[0]["pages"] == 25


# ---------------------------------------------------------------- command bar


def test_command_bar_uses_position_mode(client):
    d = cmd(client, f'alex "{TITLE_Q}" on page 40 min=20').json()
    assert d["ok"] and d["pages_added"] == 40 and d["page"] == 40
    d = cmd(client, f'alex "{TITLE_Q}" on pg 52 min=5').json()
    assert d["pages_added"] == 12 and d["minutes"] == 25
    r = rows(client)
    assert len(r) == 1 and r[0]["source"] == "position" and r[0]["source_label"] == "web"
    d = cmd(client, f'alex "{TITLE_Q}" on page 10').json()
    assert d["logged"] is False and d["message"].startswith("Already logged 52 pages")


def test_command_bar_errors(client):
    r = cmd(client, f'alex "{TITLE_Q}" on page 40 pages=3')
    assert r.status_code == 400 and "not both" in r.json()["error"]
    r = cmd(client, f'alex "{TITLE_Q}" on page 6000')
    assert r.status_code == 400
    assert rows(client) == []


def test_command_bar_unknown_book_needs_flow(client):
    d = cmd(client, 'alex "Zzyzx Quuxbert Saga" on page 12').json()
    assert d["ok"] is False and d["needs"]["reason"] == "new_book"
    d = cmd(client, 'alex "Zzyzx Quuxbert Saga" on page 12 format=early').json()
    assert d["ok"] and d["page"] == 12


# ---------------------------------------------------------------- web structured path


def test_web_page_with_typed_book(client):
    r = client.post("/api/log", json={"reader": "alex", "book": TITLE_Q, "page": 30,
                                       "minutes": 12, "source": "web"})
    d = r.json()
    assert d["ok"] and d["pages_added"] == 30 and d["book_title"]
    r = client.post("/api/log", json={"reader": "alex", "book": TITLE_Q, "page": 45,
                                       "minutes": 8, "source": "web"})
    assert r.json()["minutes"] == 20
    assert len(rows(client)) == 1


def test_web_page_with_typed_unknown_book_needs(client):
    r = client.post("/api/log", json={"reader": "alex", "book": "Zzyzx Quuxbert Saga", "page": 9})
    assert r.json()["needs"]["reason"] == "new_book" and rows(client) == []
    r = client.post("/api/log", json={"reader": "alex", "book": "Zzyzx Quuxbert Saga",
                                       "page": 9, "format": "early_chapter_book"})
    assert r.json()["ok"] and rows(client)[0]["pages"] == 9


def test_web_page_with_book_key_form_adds_minutes(client):
    body = {"reader": "alex", "book_key": KEY, "page": 20, "minutes": 10,
            "minutes_mode": "add", "source": "web"}
    client.post("/api/log", json=body)
    body.update(page=25, minutes=5)
    d = client.post("/api/log", json=body).json()
    assert d["pages_added"] == 5 and d["minutes"] == 15 and "now on page 25" in d["message"]
    assert rows(client)[0]["source_label"] == "web"


def test_web_noop_message(client):
    manual_pages(client, 68)
    d = client.post("/api/log", json={"reader": "alex", "book_key": KEY, "page": 60,
                                       "minutes_mode": "add"}).json()
    assert d["logged"] is False and d["message"] == (
        f"Already logged 68 pages of {d['book_title']}; page 60 adds nothing.")
    assert len(rows(client)) == 1


def test_scrobbler_contract_unchanged(client):
    d = scrobble(client, 20, 30)
    assert "message" not in d
    d = scrobble(client, 25, 10)  # smaller minutes: max keeps 30
    assert d["minutes"] == 30
    d = scrobble(client, 25, 40)
    assert d["minutes"] == 40 and d["logged"] and d["pages_added"] == 0
    # zero pages + minutes, no row: scrobbler still writes nothing
    manual_pages(client, 100)
    before = len(rows(client))
    d = scrobble(client, 50, 99, date="2026-11-20")
    assert d["logged"] is False and len(rows(client)) == before
    # still needs a book_key
    r = client.post("/api/log", json={"reader": "alex", "page": 10})
    assert r.status_code == 400 and "book_key" in r.json()["error"]
    r = client.post("/api/log", json={"reader": "alex", "book_key": KEY, "page": 10,
                                       "minutes_mode": "sideways"})
    assert r.status_code == 400


def test_web_pages_form_unchanged(client):
    d = client.post("/api/log", json={"reader": "alex", "book_key": KEY, "pages": 12,
                                       "minutes": 7}).json()
    assert d["ok"] and d["pages"] == 12 and "page" not in d
    assert rows(client)[0]["source"] == "manual"


# ---------------------------------------------------------------- side effects once


def test_finished_and_milestone_fire_once_across_mixed_posts(client, monkeypatch):
    monkeypatch.setattr(app_module, "MILESTONE_THRESHOLDS", [(10.0, "Tiny **10**")])
    hits = []
    monkeypatch.setattr(app_module.gcal, "post_milestone", lambda *a, **k: hits.append(a))
    seen = []
    real = app_module._process_bingo
    monkeypatch.setattr(app_module, "_process_bingo",
                        lambda *a, **k: seen.append(a[4]) or real(*a, **k))
    events = []
    events += scrobble(client, 10, 5)["events"]
    events += [slash(client, f'alex "{TITLE_Q}" on page 40 min=5')]
    events += cmd(client, f'alex "{TITLE_Q}" on page 60 finished').json()["events"]
    assert seen == [False, False, True]
    # finished is sticky and a repeat adds nothing
    cmd(client, f'alex "{TITLE_Q}" on page 60 finished')
    slash(client, f'alex "{TITLE_Q}" on page 60 finished')
    d = scrobble(client, 60, 5)
    assert d["logged"] is False and d["finished"] is True
    assert seen == [False, False, True]
    assert len(hits) == 1
    assert sum("Tiny 10" in str(e) for e in events) == 1
    assert len(rows(client)) == 1 and rows(client)[0]["finished"] == 1


def test_finish_with_nothing_new_fires_once_and_replies(client):
    scrobble(client, 30, 5)
    out = slash(client, f'alex "{TITLE_Q}" on page 30 finished')
    assert "finished" in out and "adds nothing" in out
    out2 = slash(client, f'alex "{TITLE_Q}" on page 30 finished')
    assert out2.startswith("Already logged 30 pages")
