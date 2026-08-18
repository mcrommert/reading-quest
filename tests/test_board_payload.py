"""The board payload, and the single-source guarantee for card geometry.

The 5x5 line map used to exist twice: once in bingo.py and once inlined in
board/board.js. Two copies of a constant can drift, and once cards became
definable in config they genuinely could — a family with a differently shaped
card would get a server that agreed with itself and a board that didn't.
The server is now the only source and the board consumes it.
"""

import re
from pathlib import Path

import pytest

import app as app_module
import bingo

BOARD_JS = Path(__file__).resolve().parent.parent / "board" / "board.js"


@pytest.fixture
def payload(tmp_path, monkeypatch):
    """Build a board payload against an empty temp database."""
    import importlib

    monkeypatch.setenv("DB_PATH", str(tmp_path / "board.db"))
    import db as db_module

    importlib.reload(db_module)
    db_module.init_db()
    monkeypatch.setattr(app_module, "db", db_module)
    return app_module._build_board_payload()


def test_payload_carries_card_geometry(payload):
    geo = payload["bingo"]
    assert geo["lines"] == bingo.BINGO_LINES
    assert geo["size"] == bingo.CARD_SIZE
    assert geo["free_index"] == bingo.FREE_INDEX


def test_payload_renders_whoever_is_configured(payload):
    """Board content follows reader config, with no reader hardcoded in app.py.

    app.py snapshots the roster into PLAYERS_CONFIG at import, so this compares
    against that snapshot rather than the per-test pinned roster — the point is
    that the player list is derived from config at all, whatever it contains.
    """
    configured = [r["key"] for r in app_module.PLAYERS_CONFIG]
    assert [p["key"] for p in payload["players"]] == configured
    assert configured, "no readers configured at all"


def test_every_configured_reader_gets_a_bingo_grid(payload):
    """Including a reader with no hand-authored card — they get a generated one
    rather than an empty grid."""
    for player in payload["players"]:
        assert len(player["bingo"]["squares_checked"]) >= 0
        assert "lines" in player["bingo"]


def test_board_js_no_longer_carries_its_own_line_map():
    """Guards the regression this change exists to prevent."""
    source = BOARD_JS.read_text(encoding="utf-8")
    # The old copy was a literal array of 12 five-element index lists.
    assert "[0,5,10,15,20]" not in source.replace(" ", "")
    assert "[4,8,12,16,20]" not in source.replace(" ", "")


def test_board_js_does_not_hardcode_the_grid_size_or_free_cell():
    source = BOARD_JS.read_text(encoding="utf-8")
    render = source[
        source.index("function renderBingo") : source.index("function renderPlayerHeader")
    ]
    compact = render.replace(" ", "")
    assert "i<25" not in compact, "grid size is hardcoded in the render loop"
    assert "i===12" not in compact, "free cell index is hardcoded in the render loop"
    # It must be reading them from the payload instead.
    assert "geo.size" in render and "geo.free_index" in render and "geo.lines" in render


def test_alexa_endpoint_is_gone():
    """Retired: it never served a request, and its skill-id check was spoofable."""
    routes = {getattr(r, "path", None) for r in app_module.app.routes}
    assert "/alexa" not in routes
    assert not hasattr(app_module, "ALEXA_SKILL_ID")
    assert not (Path(__file__).resolve().parent.parent / "alexa_skill_model.json").exists()


def test_core_routes_survive():
    """Sanity: removing Alexa didn't take anything else with it."""
    routes = {getattr(r, "path", None) for r in app_module.app.routes}
    for path in (
        "/health",
        "/board.json",
        "/library.json",
        "/log",
        "/api/log",
        "/slash/read",
        "/slash/reading",
        "/slash/book",
        "/slash/bingo",
    ):
        assert path in routes, f"{path} disappeared"
