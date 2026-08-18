"""
Bingo card definitions, line detection, and state helpers.

Each card is a 5×5 grid stored in row-major order.
Squares have stable IDs so display text can be edited without breaking saved state.

NOTE: Square IDs are preserved across the "minutes → pages" migration so that
any squares already checked in the database stay valid. Three squares were
relabelled (W_45_MIN, M_60_MIN, M_POETRY) — IDs unchanged.
"""

import logging
import random

from readers import get_reader

# (datetime imported locally inside auto_detect where needed)

# ── Card definitions ──────────────────────────────────────────────────────────

YOUNGER_SQUARES = [
    ("W_PILLOW_FORT", "Read in a pillow fort"),
    ("W_OUTSIDE", "Read outside"),
    ("W_FLASHLIGHT", "Read by flashlight"),
    (
        "W_NONFICTION",
        "Read a nonfiction book",
        {"finished_format": ["nonfiction"], "reason": "Finished nonfiction: {title}"},
    ),
    (
        "W_50_PAGES",
        "Read 50 pages in one day",
        {
            "daily_pages": {"gte": 50},
            "prose_only": True,
            "reason": "Read {daily_pages} pages today",
        },
    ),
    ("W_ALOUD_PET", "Read aloud to a pet"),
    ("W_ALOUD_FAMILY", "Read aloud to family"),
    ("W_NEW_AUTHOR", "Try a new author"),
    ("W_BEFORE_BREAKFAST", "Read before breakfast"),
    ("W_PAJAMAS", "Stay in pajamas to read all day"),
    (
        "W_100_PAGE_BOOK",
        "Book with 100+ pages",
        {
            "finished_format": [
                "chapter_book",
                "early_chapter_book",
                "dense_middle_grade",
                "dense_classic",
            ],
            "book_total_pages": {"gte": 100},
            "reason": "Finished {title} ({book_total_pages} pages)",
        },
    ),
    ("W_OTHER_COUNTRY", "Book set in another country"),
    ("W_FREE", "FREE SPACE"),
    ("W_FRIEND_REC", "A friend's recommendation"),
    ("W_LIBRARY", "Read at the library"),
    ("W_HARDER_BOOK", "Try a harder chapter book"),
    ("W_LAUGH", "Laugh out loud at a page"),
    ("W_2_CHAPTERS", "Read 2 chapters before bed"),
    (
        "W_FINISH_BOOK",
        "Finish a whole chapter book",
        {
            "finished_format": [
                "chapter_book",
                "early_chapter_book",
                "dense_middle_grade",
                "dense_classic",
            ],
            "reason": "Finished {title}",
        },
    ),
    (
        "W_45_MIN",
        "Read 30 pages in one sitting",
        {
            "session_pages": {"gte": 30},
            "prose_only": True,
            "reason": "Read {session_pages} pages in one sitting",
        },
    ),
    ("W_SNACK", "Read with a snack"),
    ("W_BLANKET", "Read under a blanket"),
    (
        "W_REAL_PERSON",
        "Book about a real person",
        {"finished_genre": ["biography", "memoir"], "reason": "Finished biography: {title}"},
    ),
    ("W_BOOKSTORE", "Visit a bookstore"),
    (
        "W_3_BOOKS_WEEK",
        "Read 3 books in one week",
        {
            "books_finished_week": {"gte": 3},
            "reason": "Finished {books_finished_week} books this week",
        },
    ),
]

OLDER_SQUARES = [
    ("M_HAMMOCK", "Read in a hammock or under a tree"),
    ("M_FLASHLIGHT", "Read by flashlight"),
    (
        "M_NONFICTION",
        "Read nonfiction at your level",
        {"finished_format": ["nonfiction"], "reason": "Finished nonfiction: {title}"},
    ),
    (
        "M_NEWBERY",
        "Read a Newbery winner",
        {"finished_award": ["newbery"], "reason": "Finished Newbery winner: {title}"},
    ),
    (
        "M_100_PAGES",
        "Read 100 pages in one day",
        {
            "daily_pages": {"gte": 100},
            "prose_only": True,
            "reason": "Read {daily_pages} pages today",
        },
    ),
    ("M_ALOUD_ALEX", "Read aloud to a younger reader"),
    ("M_NEW_GENRE", "Try a genre you've never tried"),
    ("M_BEFORE_BREAKFAST", "Read before breakfast"),
    ("M_PAJAMAS", "Stay in pajamas to read all day"),
    ("M_OLDER_BOOK", "Read a book older than you are"),
    ("M_OTHER_COUNTRY", "Book set in another country"),
    (
        "M_CLASSIC",
        "Read a classic (Tolkien, Le Guin, etc.)",
        {"finished_classification": ["masterpiece"], "reason": "Finished classic: {title}"},
    ),
    ("M_FREE", "FREE SPACE"),
    ("M_FRIEND_REC", "A friend's recommendation"),
    ("M_LIBRARY", "Read at the library"),
    ("M_LEVEL_UP", "Read a stretch / level-up book"),
    (
        "M_60_MIN",
        "Read 75 pages in one sitting",
        {
            "session_pages": {"gte": 75},
            "prose_only": True,
            "reason": "Read {session_pages} pages in one sitting",
        },
    ),
    ("M_POETRY", "Read a collection of poetry"),
    (
        "M_BIOGRAPHY",
        "Read a biography",
        {"finished_genre": ["biography"], "reason": "Finished biography: {title}"},
    ),
    (
        "M_SCIFI_CLASSIC",
        "Read a sci-fi classic",
        {
            "finished_classification": ["masterpiece"],
            "finished_genre": ["scifi"],
            "reason": "Finished sci-fi classic: {title}",
        },
    ),
    ("M_SNACK", "Read with a snack"),
    ("M_SEQUEL", "Read a book and its sequel"),
    ("M_BOOKSTORE", "Visit a bookstore"),
    (
        "M_3_DAYS",
        "Finish a book in 3 days",
        {
            "finished": True,
            "prose_only": True,
            "days_to_finish": {"lte": 3},
            "reason": "Finished {title} in {days_to_finish} days",
        },
    ),
    ("M_CAR", "Read on a trip / in the car"),
]

BINGO_LINE_BONUS = 25

# ── Line indices (5 rows + 5 cols + 2 diagonals = 12 lines) ──────────────────

BINGO_LINES = [
    # rows
    [0, 1, 2, 3, 4],
    [5, 6, 7, 8, 9],
    [10, 11, 12, 13, 14],
    [15, 16, 17, 18, 19],
    [20, 21, 22, 23, 24],
    # columns
    [0, 5, 10, 15, 20],
    [1, 6, 11, 16, 21],
    [2, 7, 12, 17, 22],
    [3, 8, 13, 18, 23],
    [4, 9, 14, 19, 24],
    # diagonals
    [0, 6, 12, 18, 24],
    [4, 8, 12, 16, 20],
]

LINE_LABELS = [
    "Row 1",
    "Row 2",
    "Row 3",
    "Row 4",
    "Row 5",
    "Col 1",
    "Col 2",
    "Col 3",
    "Col 4",
    "Col 5",
    "Diagonal ↘",
    "Diagonal ↙",
]


# ── State helpers ─────────────────────────────────────────────────────────────


def square_index(reader: str, square_id: str, card_num: int = 1) -> int | None:
    """Return 0-based grid index for a square ID, or None if not found."""
    squares = get_card_squares(reader, card_num)
    for i, (sid, _label, _trigger) in enumerate(squares):
        if sid == square_id:
            return i
    return None


def square_label(reader: str, square_id: str, card_num: int = 1) -> str:
    squares = get_card_squares(reader, card_num)
    for sid, label, _trigger in squares:
        if sid == square_id:
            return label
    return square_id


def find_square(reader: str, query: str, card_num: int = 1) -> tuple[str, str] | None:
    """Fuzzy-match a query to a square. Returns (square_id, label) or None."""
    squares = get_card_squares(reader, card_num)
    if not squares:
        return None
    q = query.lower().replace("_", " ").strip()
    # Exact ID match first (case-insensitive); accept the full ID or the
    # ID minus its reader prefix (e.g. "pillow_fort" → W_PILLOW_FORT)
    q_id = q.replace(" ", "_")
    for sid, label, _trigger in squares:
        sl = sid.lower()
        if sl == q_id or sl.split("_", 1)[-1] == q_id:
            return sid, label
    from rapidfuzz import process, fuzz

    # Build candidates: ID (normalised) + display text
    candidates: dict[str, tuple[str, str]] = {}
    for sid, label, _trigger in squares:
        candidates[sid.lower().replace("_", " ")] = (sid, label)
        candidates[label.lower()] = (sid, label)
    result = process.extractOne(
        q, list(candidates.keys()), scorer=fuzz.token_set_ratio, score_cutoff=55
    )
    if result:
        matched_key, score, _ = result
        return candidates[matched_key]
    return None


def check_new_lines(
    reader: str, checked_ids: set[str], already_awarded: set[str], card_num: int = 1
) -> list[tuple[str, str, list[str]]]:
    """
    Return list of (line_id, line_label, [square_labels]) for each newly
    complete line that hasn't been awarded yet.
    """
    squares = get_card_squares(reader, card_num)
    checked_ix = {i for i, sq in enumerate(squares) if sq[0] in checked_ids}
    new_lines = []
    for i, line in enumerate(BINGO_LINES):
        line_id = f"line_{i}"
        if line_id in already_awarded:
            continue
        if all(pos in checked_ix for pos in line):
            square_labels = [squares[pos][1] for pos in line]
            new_lines.append((line_id, LINE_LABELS[i], square_labels))
    return new_lines


# ── Auto-detection triggers ───────────────────────────────────────────────────
# Returns list of (square_id, reason_str) that should be auto-checked.
#
# `session_minutes` is retained in the signature for back-compat with callers,
# but no rule actually uses it — everything is page-driven now.


NON_PROSE_FORMATS = {
    "graphic_novel",
    "graphic_novel_telgemeier",
    "easy_reader",
    "picture_book",
}

# Conditions that only make sense about a book the reader just finished. Listed
# here so they can imply `finished` rather than every trigger having to repeat it.
_FINISH_CONDITIONS = {
    "finished_format": "format",
    "finished_genre": "genre",
    "finished_classification": "classification",
    "finished_award": "award",
}

# Numeric conditions and the comparators they accept.
_NUMERIC_CONDITIONS = {
    "daily_pages",
    "session_pages",
    "book_total_pages",
    "books_finished_week",
    "books_finished_total",
    "days_to_finish",
}


def _days_to_finish(first_session_date, session_date):
    """Inclusive day count from a book's first session to finishing it."""
    if not first_session_date or not session_date:
        return None
    from datetime import date

    try:
        d1 = date.fromisoformat(first_session_date)
        d2 = date.fromisoformat(session_date)
    except ValueError:
        return None
    return (d2 - d1).days + 1


def _condition_met(name, spec, ctx):
    """Evaluate one condition of a trigger against the session context."""
    if name == "reason":
        return True
    if name == "prose_only":
        return ctx["is_prose"] if spec else True
    if name == "finished":
        return ctx["finished"] is bool(spec)
    if name in _FINISH_CONDITIONS:
        if not ctx["finished"]:
            return False
        value = ctx[_FINISH_CONDITIONS[name]]
        return value in (spec if isinstance(spec, (list, tuple, set)) else [spec])
    if name in _NUMERIC_CONDITIONS:
        value = ctx[name]
        if value is None:
            return False
        if "gte" in spec and value < spec["gte"]:
            return False
        if "lte" in spec and value > spec["lte"]:
            return False
        return True
    raise ValueError(f"unknown trigger condition {name!r}")


def evaluate_triggers(squares, ctx) -> list[tuple[str, str]]:
    """Return (square_id, reason) for every square whose trigger fires.

    All conditions on a trigger must hold. Squares with no trigger are manual
    only, which is the default — a card can be entirely manual and still work.
    """
    fired = []
    for square in squares:
        if len(square) < 3 or not square[2]:
            continue
        square_id, _, trigger = square[0], square[1], square[2]
        if all(_condition_met(name, spec, ctx) for name, spec in trigger.items()):
            reason = trigger.get("reason", "Auto-checked")
            fired.append((square_id, reason.format(**ctx)))
    return fired


def auto_detect(
    reader: str,
    session_pages: int,
    session_minutes: int,
    daily_pages: int,
    book: dict,
    finished: bool,
    book_first_session_date: str | None,  # YYYY-MM-DD of first session on this book
    session_date: str,  # today YYYY-MM-DD
    books_finished_this_week: int,  # distinct books finished in last 7 days
    book_total_pages: int = 0,  # total pages logged for this book across all sessions
    card_num: int = 1,  # current bingo card number
    books_finished_total: int = 0,  # total books finished all season
) -> list[tuple[str, str]]:
    """Squares that this session should auto-check.

    Rules live on the squares themselves, so they travel with a card wherever it
    is defined — including a card written in a family's own reader config. There
    is deliberately no reader-specific logic here.
    """
    ctx = {
        "daily_pages": daily_pages,
        "session_pages": session_pages,
        "book_total_pages": book_total_pages,
        "books_finished_week": books_finished_this_week,
        "books_finished_total": books_finished_total,
        "days_to_finish": (
            _days_to_finish(book_first_session_date, session_date) if finished else None
        ),
        "finished": bool(finished),
        # Illustrated formats don't count toward page-count milestones.
        "is_prose": book.get("format") not in NON_PROSE_FORMATS,
        "format": book.get("format"),
        "genre": book.get("genre"),
        "classification": book.get("classification"),
        "award": book.get("award"),
        "title": book.get("title", "this book"),
    }
    return evaluate_triggers(get_card_squares(reader, card_num), ctx)


# ── Card 2 definitions ────────────────────────────────────────────────────────
# New squares with harder / different challenges. Auto-detectable IDs noted.

YOUNGER_SQUARES_2 = [
    (
        "W2_GRAPHIC_NOVEL",
        "Read a graphic novel",
        {
            "finished_format": ["graphic_novel", "graphic_novel_telgemeier"],
            "reason": "Finished graphic novel: {title}",
        },
    ),  # auto: format=graphic_novel
    (
        "W2_2_DAYS",
        "Finish a book in 2 days",
        {
            "finished": True,
            "prose_only": True,
            "days_to_finish": {"lte": 2},
            "reason": "Finished {title} in {days_to_finish} days",
        },
    ),  # auto
    (
        "W2_150_PAGE_BOOK",
        "Book with 150+ pages",
        {
            "finished_format": [
                "chapter_book",
                "early_chapter_book",
                "dense_middle_grade",
                "dense_classic",
            ],
            "book_total_pages": {"gte": 150},
            "reason": "Finished {title} ({book_total_pages} pages)",
        },
    ),  # auto
    ("W2_MYSTERY", "Read a mystery book"),  # manual
    ("W2_OUTSIDE_AFTNN", "Read outside for a whole afternoon"),  # manual
    ("W2_ALOUD_KID", "Read aloud to a younger kid"),  # manual
    ("W2_HISTORY", "Book set in the past"),  # manual
    ("W2_ANIMAL_BOOK", "Book with an animal hero"),  # manual
    ("W2_BEFORE_TV", "Read before any TV, 3 days"),  # manual
    ("W2_NEW_SERIES", "Start a brand-new series"),  # manual
    ("W2_FUNNY_BOOK", "A book that made you laugh out loud"),  # manual
    (
        "W2_50_PAGES_SIT",
        "Read 50 pages in one sitting",
        {
            "session_pages": {"gte": 50},
            "prose_only": True,
            "reason": "Read {session_pages} pages in one sitting",
        },
    ),  # auto
    ("W2_FREE", "FREE SPACE"),
    ("W2_REREAD", "Re-read a favourite book"),  # manual
    ("W2_RECOMMEND", "Recommend a book to a friend"),  # manual
    ("W2_SCARY", "Read something a little scary"),  # manual
    ("W2_MAGIC_BOOK", "Book with magic or fantasy"),  # manual
    (
        "W2_10_BOOKS",
        "Finish your 10th book this summer",
        {
            "books_finished_total": {"gte": 10},
            "reason": "Finished {books_finished_total} books this season",
        },
    ),  # auto
    ("W2_SERIES_2", "Read 2+ books in the same series"),  # manual (no series metadata)
    (
        "W2_100_PAGES_DAY",
        "Read 100 pages in one day",
        {
            "daily_pages": {"gte": 100},
            "prose_only": True,
            "reason": "Read {daily_pages} pages today",
        },
    ),  # auto
    ("W2_MORNING_3", "Read before breakfast 3 mornings"),  # manual
    ("W2_DIFFERENT_CTRY", "Book set in a different country"),  # manual
    ("W2_POEM_WEEK", "Read a poem every day for a week"),  # manual
    (
        "W2_3_BOOKS_WEEK",
        "Read 3 books in one week",
        {
            "books_finished_week": {"gte": 3},
            "reason": "Finished {books_finished_week} books this week",
        },
    ),  # auto
    ("W2_BLANKET_FORT", "Build a reading fort and read in it"),  # manual
]

OLDER_SQUARES_2 = [
    (
        "M2_GRAPHIC_NOVEL",
        "Read a graphic novel or manga",
        {
            "finished_format": ["graphic_novel", "graphic_novel_telgemeier"],
            "reason": "Finished graphic novel: {title}",
        },
    ),  # auto
    (
        "M2_2_DAYS",
        "Finish a book in 2 days",
        {
            "finished": True,
            "prose_only": True,
            "days_to_finish": {"lte": 2},
            "reason": "Finished {title} in {days_to_finish} days",
        },
    ),  # auto
    (
        "M2_400_PAGE_BOOK",
        "Book with 400+ pages",
        {
            "finished_format": ["chapter_book", "dense_middle_grade", "dense_classic"],
            "book_total_pages": {"gte": 400},
            "reason": "Finished {title} ({book_total_pages} pages)",
        },
    ),  # auto
    ("M2_HISTORICAL", "Historical fiction"),  # manual
    (
        "M2_200_PAGES_DAY",
        "Read 200 pages in one day",
        {
            "daily_pages": {"gte": 200},
            "prose_only": True,
            "reason": "Read {daily_pages} pages today",
        },
    ),  # auto
    ("M2_RECOMMEND_W", "Recommend a book to another reader"),  # manual
    ("M2_NEW_GENRE", "Try a genre you've never read"),  # manual
    ("M2_SERIES_3", "Read 3+ books in same series"),  # manual (no series metadata)
    ("M2_BEFORE_SCREENS", "Read before any screens, 3 days"),  # manual
    ("M2_REREAD", "Re-read a favourite book"),  # manual
    (
        "M2_CLASSIC_2",
        "Read a second classic",
        {"finished_classification": ["masterpiece"], "reason": "Finished classic: {title}"},
    ),  # auto: classification=masterpiece
    (
        "M2_100_PAGES_SIT",
        "Read 100 pages in one sitting",
        {
            "session_pages": {"gte": 100},
            "prose_only": True,
            "reason": "Read {session_pages} pages in one sitting",
        },
    ),  # auto
    ("M2_FREE", "FREE SPACE"),
    ("M2_LIBRARY_2", "Check out 3 books from the library"),  # manual
    (
        "M2_5_BOOKS",
        "Finish 5 books",
        {
            "books_finished_total": {"gte": 5},
            "reason": "Finished {books_finished_total} books this season",
        },
    ),  # auto
    ("M2_POEM", "Read a poetry collection"),  # manual
    (
        "M2_BIOGRAPHY_2",
        "Read a second biography",
        {"finished_genre": ["biography"], "reason": "Finished biography: {title}"},
    ),  # auto
    ("M2_AUDIOBOOK", "Listen to an audiobook"),  # manual
    (
        "M2_NEWBERY_2",
        "Read a second Newbery winner",
        {"finished_award": ["newbery"], "reason": "Finished Newbery winner: {title}"},
    ),  # auto
    ("M2_REVIEW", "Write a book review"),  # manual
    ("M2_MORNING_WEEK", "Read every morning for a week"),  # manual
    ("M2_LONG_SITTING", "Read for 2 hours straight"),  # manual
    (
        "M2_10_BOOKS",
        "Finish 10 books",
        {
            "books_finished_total": {"gte": 10},
            "reason": "Finished {books_finished_total} books this season",
        },
    ),  # auto
    (
        "M2_SCIFI_2",
        "Read a second sci-fi book",
        {"finished_genre": ["scifi"], "reason": "Finished sci-fi: {title}"},
    ),  # auto
    ("M2_BUDDY_READ", "Read the same book as another reader"),  # manual
]

# ── Card sets ────────────────────────────────────────────────────────────────
# Named sets of cards, selected per reader by the "card" key in reader config.
# Named after the reading stage they suit, never after a particular child, so a
# family can point any reader at either one. A reader with no "card" key gets a
# generated card, so bingo works out of the box for a newly added reader.
#
# Square IDs are deliberately unchanged from when these were keyed on reader
# names: saved bingo state references them, and renaming would orphan it.

CARD_SETS: dict[str, dict[int, list]] = {
    "younger": {1: YOUNGER_SQUARES, 2: YOUNGER_SQUARES_2},
    "older": {1: OLDER_SQUARES, 2: OLDER_SQUARES_2},
}


# Default bingo card for readers without a hand-authored one (e.g. a newly
# added kid). Square IDs are generated per-reader (prefixed by reader key) so
# cards never collide. FREE SPACE sits at the centre (index 12). Generic
# reading-challenge prompts — override per reader by adding an entry to
# CARDS_BY_NUM keyed on that reader's key.
DEFAULT_CARD_TEMPLATE = [
    ("PILLOW_FORT", "Read in a pillow fort"),
    ("OUTSIDE", "Read outside"),
    ("FLASHLIGHT", "Read by flashlight"),
    ("NONFICTION", "Read a nonfiction book"),
    ("BIG_DAY", "Read a lot in one day"),
    ("ALOUD_PET", "Read aloud to a pet"),
    ("ALOUD_FAMILY", "Read aloud to family"),
    ("NEW_AUTHOR", "Try a new author"),
    ("BEFORE_BREAKFAST", "Read before breakfast"),
    ("PAJAMAS", "Stay in pajamas to read all day"),
    ("LONG_BOOK", "Read a longer book"),
    ("OTHER_COUNTRY", "Book set in another country"),
    ("FREE", "FREE SPACE"),
    ("FRIEND_REC", "A friend's recommendation"),
    ("LIBRARY", "Read at the library"),
    ("HARDER_BOOK", "Try a harder book"),
    ("LAUGH", "Laugh out loud at a page"),
    ("BEFORE_BED", "Read before bed"),
    ("FINISH_BOOK", "Finish a whole book"),
    ("BIG_SITTING", "Read a lot in one sitting"),
    ("SNACK", "Read with a snack"),
    ("BLANKET", "Read under a blanket"),
    ("REAL_PERSON", "Book about a real person"),
    ("BOOKSTORE", "Visit a bookstore"),
    ("SEVERAL_BOOKS", "Read several books in a week"),
]


# A card is a 5x5 grid, so exactly 25 squares with FREE in the middle. The line
# map, the board's mini-grid and its CSS all assume this. Cards can now come
# from user config, so the assumption has to be checked rather than trusted.
CARD_SIZE = 25
FREE_INDEX = 12


def _is_free_id(square_id: str) -> bool:
    """Whether a square ID names the free space.

    Exact suffix, never a substring: a user square such as X_FREEZE_TAG contains
    "FREE" but is an ordinary square, and treating it as the free space would
    silently break the centre of the grid.
    """
    sid = (square_id or "").upper()
    return sid == "FREE" or sid.endswith("_FREE")


def validate_card(squares, origin: str) -> list[tuple]:
    """Check a card's shape, or raise ValueError naming what's wrong.

    Fails loudly at load rather than rendering a subtly broken board: a card of
    the wrong length produces lines that can never complete, and a misplaced
    FREE square breaks the middle row, middle column and both diagonals at once.
    """
    squares = [(sq[0], sq[1], sq[2] if len(sq) > 2 else None) for sq in squares]
    if len(squares) != CARD_SIZE:
        raise ValueError(f"{origin}: needs exactly {CARD_SIZE} squares, got {len(squares)}")
    ids = [s[0] for s in squares]
    if len(set(ids)) != CARD_SIZE:
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"{origin}: duplicate square IDs {dupes}")
    free_positions = [i for i, sid in enumerate(ids) if _is_free_id(sid)]
    if free_positions != [FREE_INDEX]:
        raise ValueError(
            f"{origin}: expected exactly one FREE square at index {FREE_INDEX}, "
            f"found {free_positions}"
        )
    return squares


def _generated_card(reader: str, card_num: int = 1) -> list[tuple]:
    """Build a default card for a reader with per-reader-prefixed square IDs.

    Cards past the first are shuffled so a reader who works through several
    doesn't simply replay the same grid while the line bonus keeps doubling.
    The shuffle is seeded on (reader, card_num) so a given card is stable across
    restarts, and FREE stays pinned to the centre.
    """
    prefix = (reader or "R").upper()
    suffix_prefix = "" if card_num <= 1 else f"{card_num}"
    squares = [
        (f"{prefix}{suffix_prefix}_{suffix}", label) for suffix, label in DEFAULT_CARD_TEMPLATE
    ]
    if card_num > 1:
        free = squares[FREE_INDEX]
        rest = squares[:FREE_INDEX] + squares[FREE_INDEX + 1 :]
        random.Random(f"{reader}:{card_num}").shuffle(rest)
        squares = rest[:FREE_INDEX] + [free] + rest[FREE_INDEX:]
    return validate_card(squares, f"generated card {card_num} for {reader!r}")


_warned_readers: set[str] = set()


def _warn_generated_card(reader: str) -> None:
    """Warn once per reader that they are on a generated card."""
    if reader in _warned_readers:
        return
    _warned_readers.add(reader)
    logging.getLogger(__name__).warning(
        "reader %r has no 'card' in reader config, so they get a generated bingo "
        "card. If they had squares checked previously, those IDs are not on this "
        'card. Set "card": "younger" or "older" (see reader_config_example.py).',
        reader,
    )


def cards_for_reader(reader: str) -> dict[int, list] | None:
    """Resolve a reader's hand-authored cards from config, or None.

    Two ways to specify them, checked in order:

      "cards": {1: [...], 2: [...]}   squares written inline, full control
      "card":  "younger"              a named set from CARD_SETS

    Inline wins, so a family can start from a named set and override one card.
    """
    cfg = get_reader(reader) or {}
    inline = cfg.get("cards")
    if inline:
        return {int(num): squares for num, squares in inline.items()}
    name = cfg.get("card")
    if name is None:
        return None
    if name not in CARD_SETS:
        raise ValueError(
            f"reader {reader!r} requests unknown card set {name!r}; "
            f"available: {sorted(CARD_SETS)}"
        )
    return CARD_SETS[name]


def get_card_squares(reader: str, card_num: int) -> list[tuple]:
    """Return the square list for a given reader and card number.

    A reader whose config names a card set (or supplies squares inline) uses it
    verbatim — that is what keeps existing checked squares valid. Any other
    reader, and any card number past the ones authored, gets a generated card so
    bingo works out of the box for a newly added reader and keeps working past
    the last hand-written card.
    """
    cards = cards_for_reader(reader)
    if cards and card_num in cards:
        return validate_card(cards[card_num], f"card {card_num} for reader {reader!r}")
    if cards is None and card_num == 1:
        # Worth saying out loud once: a reader whose config predates the "card"
        # key silently drops to a generic card, and any bingo squares they had
        # already checked reference IDs that are no longer on their grid.
        _warn_generated_card(reader)
    return _generated_card(reader, card_num)


def get_free_square(reader: str, card_num: int) -> str | None:
    """Return the free square ID for this card.

    Positional, not a name match: the centre square *is* the free space, and the
    board renders index 12 as free regardless of what it is called. Matching on
    the substring "FREE" would pick up a user's square like FREEZE_TAG.
    """
    squares = get_card_squares(reader, card_num)
    if len(squares) <= FREE_INDEX:
        return None
    return squares[FREE_INDEX][0]


def line_bonus(card_num: int) -> int:
    """Points awarded per completed bingo line. Doubles each card."""
    return BINGO_LINE_BONUS * (2 ** (card_num - 1))


def total_lines() -> int:
    return len(BINGO_LINES)
