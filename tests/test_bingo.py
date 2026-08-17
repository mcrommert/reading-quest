"""Bingo geometry and card invariants.

These pin behaviour that the 2.0.0 refactor is about to move around. Cards are
becoming config-defined, which means assumptions currently guaranteed by
hand-written code (25 squares, FREE at the centre, a 5x5 line map) stop being
guaranteed and have to be asserted instead.
"""

import pytest

import bingo


ALL_CARD_NUMS = sorted(bingo.CARDS_BY_NUM)
KNOWN_READERS = sorted(bingo.CARDS_BY_NUM[1])


@pytest.mark.parametrize("card_num", ALL_CARD_NUMS)
@pytest.mark.parametrize("reader", KNOWN_READERS)
def test_hand_authored_cards_are_five_by_five(reader, card_num):
    """Every shipped card must be exactly 25 squares with unique IDs.

    BINGO_LINES indexes positions 0-24 directly, so any other length silently
    produces lines that can never complete (too few) or squares that can never
    appear in a line (too many).
    """
    squares = bingo.get_card_squares(reader, card_num)
    assert len(squares) == 25, f"{reader} card {card_num} has {len(squares)} squares"
    ids = [sid for sid, _ in squares]
    assert len(set(ids)) == 25, f"{reader} card {card_num} has duplicate square IDs"


@pytest.mark.parametrize("card_num", ALL_CARD_NUMS)
@pytest.mark.parametrize("reader", KNOWN_READERS)
def test_exactly_one_free_square_at_the_centre(reader, card_num):
    """FREE must sit at index 12 — board.js hardcodes `i === 12` as the free cell,
    and both diagonals plus the middle row and column run through it."""
    squares = bingo.get_card_squares(reader, card_num)
    free_positions = [i for i, (sid, _) in enumerate(squares) if "FREE" in sid]
    assert free_positions == [12], (
        f"{reader} card {card_num}: expected one FREE at index 12, got {free_positions}"
    )
    assert bingo.get_free_square(reader, card_num) == squares[12][0]


def test_line_map_is_a_complete_five_by_five():
    """12 lines: 5 rows, 5 columns, 2 diagonals — and every cell covered."""
    assert len(bingo.BINGO_LINES) == 12
    assert len(bingo.LINE_LABELS) == len(bingo.BINGO_LINES)
    assert all(len(line) == 5 for line in bingo.BINGO_LINES)
    covered = {i for line in bingo.BINGO_LINES for i in line}
    assert covered == set(range(25)), "some grid positions belong to no line"
    # The centre is the most-covered cell: middle row, middle column, both diagonals.
    centre_lines = [ln for ln in bingo.BINGO_LINES if 12 in ln]
    assert len(centre_lines) == 4


def test_completing_a_row_awards_exactly_one_line():
    reader, card = KNOWN_READERS[0], 1
    squares = bingo.get_card_squares(reader, card)
    top_row = {squares[i][0] for i in range(5)}
    new = bingo.check_new_lines(reader, top_row, set(), card_num=card)
    assert len(new) == 1
    line_id, label, labels = new[0]
    assert line_id == "line_0" and label == "Row 1"
    assert len(labels) == 5


def test_already_awarded_lines_are_not_re_awarded():
    reader, card = KNOWN_READERS[0], 1
    squares = bingo.get_card_squares(reader, card)
    top_row = {squares[i][0] for i in range(5)}
    assert bingo.check_new_lines(reader, top_row, {"line_0"}, card_num=card) == []


def test_a_full_card_completes_every_line():
    reader, card = KNOWN_READERS[0], 1
    all_ids = {sid for sid, _ in bingo.get_card_squares(reader, card)}
    new = bingo.check_new_lines(reader, all_ids, set(), card_num=card)
    assert len(new) == len(bingo.BINGO_LINES) == bingo.total_lines()


def test_line_bonus_doubles_per_card():
    assert bingo.line_bonus(1) == bingo.BINGO_LINE_BONUS
    assert bingo.line_bonus(2) == bingo.BINGO_LINE_BONUS * 2
    assert bingo.line_bonus(3) == bingo.BINGO_LINE_BONUS * 4


def test_unknown_reader_gets_a_usable_generated_card():
    """A newly configured reader with no hand-authored card must still work."""
    squares = bingo.get_card_squares("brandnew", 1)
    assert len(squares) == 25
    ids = [sid for sid, _ in squares]
    assert len(set(ids)) == 25
    assert all(sid.startswith("BRANDNEW_") for sid in ids)
    # Generated IDs must not collide with the hand-authored cards.
    known = {sid for r in KNOWN_READERS for sid, _ in bingo.get_card_squares(r, 1)}
    assert not (set(ids) & known)


def test_square_lookup_round_trips():
    reader, card = KNOWN_READERS[0], 1
    for index, (sid, label) in enumerate(bingo.get_card_squares(reader, card)):
        assert bingo.square_index(reader, sid, card) == index
        assert bingo.square_label(reader, sid, card) == label


def test_find_square_matches_id_and_display_text():
    reader, card = KNOWN_READERS[0], 1
    sid, label = bingo.get_card_squares(reader, card)[0]
    assert bingo.find_square(reader, sid, card)[0] == sid
    assert bingo.find_square(reader, label, card)[0] == sid
    # ID minus its reader prefix is accepted too ("pillow_fort" -> W_PILLOW_FORT)
    suffix = sid.split("_", 1)[1].lower().replace("_", " ")
    assert bingo.find_square(reader, suffix, card)[0] == sid


@pytest.mark.xfail(
    reason="known gap: cards 3+ silently re-serve card 1 while line_bonus keeps "
           "doubling. Fixed in 2.0.0 by generating distinct cards past the "
           "hand-authored ones.",
    strict=True,
)
def test_card_three_is_not_a_duplicate_of_card_one():
    reader = KNOWN_READERS[0]
    assert bingo.get_card_squares(reader, 3) != bingo.get_card_squares(reader, 1)
