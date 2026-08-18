"""Bingo geometry and card invariants.

These pin behaviour that the 2.0.0 refactor is about to move around. Cards are
becoming config-defined, which means assumptions currently guaranteed by
hand-written code (25 squares, FREE at the centre, a 5x5 line map) stop being
guaranteed and have to be asserted instead.
"""

import pytest

import bingo


# Card numbers every shipped set defines, and the readers the pinned test roster
# points at those sets. Both come from config now rather than reader-keyed dicts.
def ids(card):
    """Square IDs of a card. Squares are (id, label, trigger|None) after
    validation, so tests index rather than unpack."""
    return [sq[0] for sq in card]


def pairs(card):
    """(id, label) of each square — the part a config author writes."""
    return [(sq[0], sq[1]) for sq in card]


ALL_CARD_NUMS = sorted(bingo.CARD_SETS["younger"])
KNOWN_READERS = ["alex", "sam"]


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
    card_ids = ids(squares)
    assert len(set(card_ids)) == 25, f"{reader} card {card_num} has duplicate square IDs"


@pytest.mark.parametrize("card_num", ALL_CARD_NUMS)
@pytest.mark.parametrize("reader", KNOWN_READERS)
def test_exactly_one_free_square_at_the_centre(reader, card_num):
    """FREE must sit at index 12 — board.js hardcodes `i === 12` as the free cell,
    and both diagonals plus the middle row and column run through it."""
    squares = bingo.get_card_squares(reader, card_num)
    free_positions = [i for i, sq in enumerate(squares) if bingo._is_free_id(sq[0])]
    assert free_positions == [
        12
    ], f"{reader} card {card_num}: expected one FREE at index 12, got {free_positions}"
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
    all_ids = set(ids(bingo.get_card_squares(reader, card)))
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
    card_ids = ids(squares)
    assert len(set(card_ids)) == 25
    assert all(sid.startswith("BRANDNEW_") for sid in card_ids)
    # Generated IDs must not collide with the hand-authored cards.
    known = {sid for r in KNOWN_READERS for sid in ids(bingo.get_card_squares(r, 1))}
    assert not (set(card_ids) & known)


class TestCardSelectionIsConfigDriven:
    """Which card a reader gets is now config, not a name baked into bingo.py.

    This is the property the whole N-reader refactor rests on: adding a child is
    a reader_config.py edit, with no code change anywhere.
    """

    def _set_readers(self, monkeypatch, readers_list):
        import readers

        monkeypatch.setattr(readers, "READERS", readers_list, raising=False)
        monkeypatch.setattr(
            readers, "READERS_BY_KEY", {r["key"]: r for r in readers_list}, raising=False
        )

    def test_named_card_set_is_used_verbatim(self):
        """The pinned roster points alex at 'younger', so it must get those squares
        — IDs included, which is what keeps saved bingo state valid."""
        assert pairs(bingo.get_card_squares("alex", 1)) == pairs(bingo.CARD_SETS["younger"][1])
        assert pairs(bingo.get_card_squares("sam", 2)) == pairs(bingo.CARD_SETS["older"][2])

    def test_any_reader_can_use_any_card_set(self, monkeypatch):
        """Sets are named for a reading stage, not a child."""
        self._set_readers(monkeypatch, [{"key": "kim", "level": "developing", "card": "older"}])
        assert pairs(bingo.get_card_squares("kim", 1)) == pairs(bingo.CARD_SETS["older"][1])

    def test_reader_without_a_card_key_gets_a_generated_card(self, monkeypatch):
        self._set_readers(monkeypatch, [{"key": "kim", "level": "developing"}])
        squares = bingo.get_card_squares("kim", 1)
        assert len(squares) == 25
        assert all(sid.startswith("KIM_") for sid in ids(squares))

    def test_inline_squares_override_a_named_set(self, monkeypatch):
        custom = [(f"K_S{i}", f"square {i}") for i in range(25)]
        custom[12] = ("K_FREE", "FREE SPACE")
        self._set_readers(
            monkeypatch,
            [{"key": "kim", "level": "developing", "card": "younger", "cards": {1: custom}}],
        )
        assert pairs(bingo.get_card_squares("kim", 1)) == pairs(custom)

    def test_inline_squares_are_validated(self, monkeypatch):
        """A hand-written card is exactly where a 24-square mistake happens."""
        self._set_readers(
            monkeypatch,
            [{"key": "kim", "level": "developing", "cards": {1: [("K_A", "a")] * 3}}],
        )
        with pytest.raises(ValueError, match="exactly 25 squares"):
            bingo.get_card_squares("kim", 1)

    def test_unknown_card_set_fails_loudly(self, monkeypatch):
        """A typo in config must not silently degrade to a generic card."""
        self._set_readers(monkeypatch, [{"key": "kim", "level": "developing", "card": "middle"}])
        with pytest.raises(ValueError, match="unknown card set"):
            bingo.get_card_squares("kim", 1)

    def test_no_reader_name_remains_in_the_card_definitions(self):
        """Guards the regression: sample-family names leaking back into cards."""
        import inspect

        source = inspect.getsource(bingo)
        card_section = source.split("# ── Auto-detection triggers")[0]
        for name in ("alex", "sam"):
            assert (
                f'"{name}"' not in card_section.lower()
            ), f"reader name {name!r} is back in the card definitions"


def test_square_lookup_round_trips():
    reader, card = KNOWN_READERS[0], 1
    for index, (sid, label, _trigger) in enumerate(bingo.get_card_squares(reader, card)):
        assert bingo.square_index(reader, sid, card) == index
        assert bingo.square_label(reader, sid, card) == label


def test_find_square_matches_id_and_display_text():
    reader, card = KNOWN_READERS[0], 1
    sid, label = bingo.get_card_squares(reader, card)[0][:2]
    assert bingo.find_square(reader, sid, card)[0] == sid
    assert bingo.find_square(reader, label, card)[0] == sid
    # ID minus its reader prefix is accepted too ("pillow_fort" -> W_PILLOW_FORT)
    suffix = sid.split("_", 1)[1].lower().replace("_", " ")
    assert bingo.find_square(reader, suffix, card)[0] == sid


def test_cards_past_the_authored_ones_are_distinct():
    """Cards 3+ used to silently re-serve card 1 while line_bonus kept doubling —
    flat difficulty, exponentially growing reward."""
    reader = KNOWN_READERS[0]
    card1 = bingo.get_card_squares(reader, 1)
    card3 = bingo.get_card_squares(reader, 3)
    card4 = bingo.get_card_squares(reader, 4)
    assert card3 != card1
    assert card3 != card4
    for card, num in ((card3, 3), (card4, 4)):
        assert len(card) == 25
        assert len(set(ids(card))) == 25
        assert bingo.get_free_square(reader, num) == card[12][0]


def test_generated_cards_are_stable_across_calls():
    """Seeded on (reader, card_num), so a card doesn't reshuffle on restart —
    otherwise saved square state would point at a grid that no longer exists."""
    reader = KNOWN_READERS[0]
    assert bingo.get_card_squares(reader, 3) == bingo.get_card_squares(reader, 3)
    assert bingo.get_card_squares("someone_else", 3) != bingo.get_card_squares(reader, 3)


def test_free_square_is_positional_not_a_name_match():
    """A user square containing the letters FREE must not hijack the centre."""
    squares = [(f"X_S{i}", f"square {i}") for i in range(25)]
    squares[12] = ("X_FREE", "FREE SPACE")
    squares[3] = ("X_FREEZE_TAG", "Read after freeze tag")
    validated = bingo.validate_card(squares, "test card")
    assert validated[bingo.FREE_INDEX][0] == "X_FREE"


class TestCardValidation:
    """Config-defined cards mean the 5x5 assumption must be checked, not trusted."""

    def _card(self):
        squares = [(f"X_S{i}", f"square {i}") for i in range(25)]
        squares[12] = ("X_FREE", "FREE SPACE")
        return squares

    def test_accepts_a_well_formed_card(self):
        assert len(bingo.validate_card(self._card(), "ok")) == 25

    def test_rejects_wrong_length(self):
        with pytest.raises(ValueError, match="exactly 25 squares"):
            bingo.validate_card(self._card()[:24], "short card")

    def test_rejects_duplicate_ids(self):
        card = self._card()
        card[5] = card[6]
        with pytest.raises(ValueError, match="duplicate square IDs"):
            bingo.validate_card(card, "dupe card")

    def test_rejects_free_square_off_centre(self):
        card = self._card()
        card[12] = ("X_S12", "square 12")
        card[0] = ("X_FREE", "FREE SPACE")
        with pytest.raises(ValueError, match="FREE square at index 12"):
            bingo.validate_card(card, "misplaced free")

    def test_rejects_missing_free_square(self):
        card = self._card()
        card[12] = ("X_S12", "square 12")
        with pytest.raises(ValueError, match="FREE square at index 12"):
            bingo.validate_card(card, "no free")
