"""The web bingo API.

Before this existed, square *labels* were reachable only through the Mattermost
slash command, and `/bingo check` was the only way to tick an honour-system
square. Any deployment without Mattermost — which is the default, since the web
logging page needs nothing else installed — simply could not use two thirds of
the bingo card. These tests cover the browser-facing replacement.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

import app as app_module
import bingo


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App wired to an empty temp database, with no PIN configured."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "bingo_web.db"))
    import db as db_module

    importlib.reload(db_module)
    db_module.init_db()
    monkeypatch.setattr(app_module, "db", db_module)
    monkeypatch.setattr(app_module, "LOG_PIN", "")
    return TestClient(app_module.app)


def squares_for(reader="alex"):
    return bingo.get_card_squares(reader, 1)


def a_manual_square(reader="alex"):
    """A square that does not auto-check and is not the free space."""
    free = bingo.get_free_square(reader, 1)
    for sid, _label, trigger in squares_for(reader):
        if not trigger and sid != free:
            return sid
    raise AssertionError("no manual square on the card")


# ── read ──────────────────────────────────────────────────────────────────────


def test_get_returns_labels_not_just_state(client):
    """The whole point: the browser can see what each square SAYS."""
    r = client.get("/api/bingo", params={"reader": "alex"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert len(d["squares"]) == bingo.CARD_SIZE
    assert all(s["label"] for s in d["squares"])
    assert [s["id"] for s in d["squares"]] == [s[0] for s in squares_for()]


def test_get_matches_card_geometry(client):
    d = client.get("/api/bingo", params={"reader": "alex"}).json()
    assert d["size"] == bingo.CARD_SIZE
    assert d["free_index"] == bingo.FREE_INDEX
    assert d["lines"] == bingo.BINGO_LINES


def test_get_marks_which_squares_check_themselves(client):
    """The UI needs this to tell a child which squares they must tick by hand."""
    d = client.get("/api/bingo", params={"reader": "alex"}).json()
    expected = {sid for sid, _l, trig in squares_for() if trig}
    assert {s["id"] for s in d["squares"] if s["auto"]} == expected
    assert expected, "fixture card has no auto squares; test proves nothing"


def test_get_flags_the_free_square_positionally(client):
    d = client.get("/api/bingo", params={"reader": "alex"}).json()
    free = [s for s in d["squares"] if s["free"]]
    assert len(free) == 1
    assert free[0]["index"] == bingo.FREE_INDEX


def test_get_rejects_unknown_reader(client):
    assert client.get("/api/bingo", params={"reader": "nobody"}).status_code == 400


def test_readers_do_not_share_state(client):
    sid = a_manual_square("alex")
    client.post("/api/bingo", json={"reader": "alex", "square_id": sid, "checked": True})
    other = client.get("/api/bingo", params={"reader": "sam"}).json()
    assert not any(s["checked"] for s in other["squares"] if not s["free"])


# ── write ─────────────────────────────────────────────────────────────────────


def test_check_then_uncheck_round_trips(client):
    sid = a_manual_square()
    up = client.post("/api/bingo", json={"reader": "alex", "square_id": sid, "checked": True})
    assert up.status_code == 200 and up.json()["changed"] is True
    assert next(s for s in up.json()["squares"] if s["id"] == sid)["checked"] is True

    down = client.post("/api/bingo", json={"reader": "alex", "square_id": sid, "checked": False})
    assert down.json()["changed"] is True
    assert next(s for s in down.json()["squares"] if s["id"] == sid)["checked"] is False


def test_checking_twice_reports_no_change(client):
    sid = a_manual_square()
    client.post("/api/bingo", json={"reader": "alex", "square_id": sid, "checked": True})
    again = client.post("/api/bingo", json={"reader": "alex", "square_id": sid, "checked": True})
    assert again.status_code == 200
    assert again.json()["changed"] is False


def test_unknown_square_id_is_rejected_not_stored(client):
    """square_label() returns the ID it was given when it doesn't match, so it
    cannot be used to validate. A bad ID must not become a phantom checked square."""
    r = client.post(
        "/api/bingo",
        json={"reader": "alex", "square_id": "NOT_A_REAL_SQUARE", "checked": True},
    )
    assert r.status_code == 400
    after = client.get("/api/bingo", params={"reader": "alex"}).json()
    assert "NOT_A_REAL_SQUARE" not in {s["id"] for s in after["squares"]}
    assert not any(s["checked"] for s in after["squares"] if not s["free"])


def test_completing_a_line_awards_the_bonus(client):
    """Checking a full row must pay out exactly like the slash command does."""
    sqs = squares_for()
    row = bingo.BINGO_LINES[0]
    for pos in row:
        client.post(
            "/api/bingo",
            json={"reader": "alex", "square_id": sqs[pos][0], "checked": True},
        )
    d = client.get("/api/bingo", params={"reader": "alex"}).json()
    assert d["lines_count"] == 1
    assert d["lines_awarded"] == ["line_0"]
    assert d["pts_bonus"] == bingo.line_bonus(1)


def test_line_completion_is_reported_on_the_response(client):
    sqs = squares_for()
    row = bingo.BINGO_LINES[0]
    last = None
    for pos in row:
        last = client.post(
            "/api/bingo",
            json={"reader": "alex", "square_id": sqs[pos][0], "checked": True},
        ).json()
    assert last["events"], "the response should tell the user a line completed"
    assert any("line" in e.lower() for e in last["events"])


def test_unchecking_a_square_takes_back_the_line_bonus(client):
    """Undo must actually undo.

    The slash command's original rule was "points already awarded are kept",
    which was safe when checking meant typing a command. On a tap grid a mis-tap
    is one finger, and a stuck +25 with an empty card is exactly the bug this
    replaced: squares unchecked, yet lines/bonus frozen on the board.
    """
    sqs = squares_for()
    row = bingo.BINGO_LINES[0]
    for pos in row:
        client.post(
            "/api/bingo", json={"reader": "alex", "square_id": sqs[pos][0], "checked": True}
        )
    assert client.get("/api/bingo", params={"reader": "alex"}).json()[
        "pts_bonus"
    ] == bingo.line_bonus(1)

    undo = client.post(
        "/api/bingo", json={"reader": "alex", "square_id": sqs[row[0]][0], "checked": False}
    ).json()
    assert undo["lines_count"] == 0
    assert undo["lines_awarded"] == []
    assert undo["pts_bonus"] == 0
    assert any("no longer complete" in e.lower() for e in undo["events"])


def test_revoking_a_line_removes_its_points_from_the_total(client):
    """The bonus is stored as a synthetic session, so revoking must drop that row
    or the points stay on the board even after the line is gone."""
    sqs = squares_for()
    row = bingo.BINGO_LINES[0]
    for pos in row:
        client.post(
            "/api/bingo", json={"reader": "alex", "square_id": sqs[pos][0], "checked": True}
        )
    with_line = client.post(
        "/api/bingo", json={"reader": "alex", "square_id": sqs[row[0]][0], "checked": True}
    ).json()["total_pts"]
    assert with_line == bingo.line_bonus(1)

    after = client.post(
        "/api/bingo", json={"reader": "alex", "square_id": sqs[row[0]][0], "checked": False}
    ).json()
    assert after["total_pts"] == 0


def test_relines_cleanly_after_a_revoke(client):
    """Re-checking the same square must re-award, not stay silently revoked."""
    sqs = squares_for()
    row = bingo.BINGO_LINES[0]
    for pos in row:
        client.post(
            "/api/bingo", json={"reader": "alex", "square_id": sqs[pos][0], "checked": True}
        )
    client.post(
        "/api/bingo", json={"reader": "alex", "square_id": sqs[row[0]][0], "checked": False}
    )
    again = client.post(
        "/api/bingo", json={"reader": "alex", "square_id": sqs[row[0]][0], "checked": True}
    ).json()
    assert again["lines_count"] == 1
    assert again["pts_bonus"] == bingo.line_bonus(1)
    assert again["total_pts"] == bingo.line_bonus(1)


def test_unrelated_lines_survive_a_revoke(client):
    """Breaking one line must not take down a line that is still complete."""
    sqs = squares_for()
    for pos in set(bingo.BINGO_LINES[0]) | set(bingo.BINGO_LINES[1]):
        client.post(
            "/api/bingo", json={"reader": "alex", "square_id": sqs[pos][0], "checked": True}
        )
    before = client.get("/api/bingo", params={"reader": "alex"}).json()
    assert before["lines_count"] >= 2

    after = client.post(
        "/api/bingo",
        json={"reader": "alex", "square_id": sqs[bingo.BINGO_LINES[0][0]][0], "checked": False},
    ).json()
    assert "line_1" in after["lines_awarded"]
    assert "line_0" not in after["lines_awarded"]


# ── PIN ───────────────────────────────────────────────────────────────────────


def test_writes_require_the_pin_when_one_is_set(client, monkeypatch):
    """This endpoint mutates score. It must be behind the same gate as /api/log —
    unlike the slash endpoints, which skip their check entirely when unset."""
    monkeypatch.setattr(app_module, "LOG_PIN", "4821")
    sid = a_manual_square()

    for body in (
        {"reader": "alex", "square_id": sid, "checked": True},
        {"reader": "alex", "square_id": sid, "checked": True, "pin": "0000"},
    ):
        assert client.post("/api/bingo", json=body).status_code == 403

    ok = client.post(
        "/api/bingo",
        json={"reader": "alex", "square_id": sid, "checked": True, "pin": "4821"},
    )
    assert ok.status_code == 200 and ok.json()["changed"] is True


def test_pin_also_accepted_as_a_header(client, monkeypatch):
    monkeypatch.setattr(app_module, "LOG_PIN", "4821")
    r = client.post(
        "/api/bingo",
        json={"reader": "alex", "square_id": a_manual_square(), "checked": True},
        headers={"X-Log-Pin": "4821"},
    )
    assert r.status_code == 200


def test_reading_the_card_does_not_require_a_pin(client, monkeypatch):
    """Same posture as /board.json — state is readable, mutation is not."""
    monkeypatch.setattr(app_module, "LOG_PIN", "4821")
    assert client.get("/api/bingo", params={"reader": "alex"}).status_code == 200


# ── the UI is wired to the API it claims to use ───────────────────────────────


def test_log_page_offers_a_bingo_mode():
    """Guards the actual gap this closed: a browser route to the squares."""
    from pathlib import Path

    html = (Path(__file__).resolve().parent.parent / "board" / "log.html").read_text(
        encoding="utf-8"
    )
    assert 'id="mode-bingo"' in html
    assert "/api/bingo" in html
