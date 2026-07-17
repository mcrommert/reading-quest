"""
Bingo card definitions, line detection, and state helpers.

Each card is a 5×5 grid stored in row-major order.
Squares have stable IDs so display text can be edited without breaking saved state.

NOTE: Square IDs are preserved across the "minutes → pages" migration so that
any squares already checked in the database stay valid. Three squares were
relabelled (W_45_MIN, M_60_MIN, M_POETRY) — IDs unchanged.
"""

# (datetime imported locally inside auto_detect where needed)

# ── Card definitions ──────────────────────────────────────────────────────────

ALEX_SQUARES = [
    ("W_PILLOW_FORT", "Read in a pillow fort"),
    ("W_OUTSIDE", "Read outside"),
    ("W_FLASHLIGHT", "Read by flashlight"),
    ("W_NONFICTION", "Read a nonfiction book"),
    ("W_50_PAGES", "Read 50 pages in one day"),
    ("W_ALOUD_PET", "Read aloud to a pet"),
    ("W_ALOUD_FAMILY", "Read aloud to family"),
    ("W_NEW_AUTHOR", "Try a new author"),
    ("W_BEFORE_BREAKFAST", "Read before breakfast"),
    ("W_PAJAMAS", "Stay in pajamas to read all day"),
    ("W_100_PAGE_BOOK", "Book with 100+ pages"),
    ("W_OTHER_COUNTRY", "Book set in another country"),
    ("W_FREE", "FREE SPACE"),
    ("W_FRIEND_REC", "A friend's recommendation"),
    ("W_LIBRARY", "Read at the library"),
    ("W_HARDER_BOOK", "Try a harder chapter book"),
    ("W_LAUGH", "Laugh out loud at a page"),
    ("W_2_CHAPTERS", "Read 2 chapters before bed"),
    ("W_FINISH_BOOK", "Finish a whole chapter book"),
    ("W_45_MIN", "Read 30 pages in one sitting"),
    ("W_SNACK", "Read with a snack"),
    ("W_BLANKET", "Read under a blanket"),
    ("W_REAL_PERSON", "Book about a real person"),
    ("W_BOOKSTORE", "Visit a bookstore"),
    ("W_3_BOOKS_WEEK", "Read 3 books in one week"),
]

SAM_SQUARES = [
    ("M_HAMMOCK", "Read in a hammock or under a tree"),
    ("M_FLASHLIGHT", "Read by flashlight"),
    ("M_NONFICTION", "Read nonfiction at your level"),
    ("M_NEWBERY", "Read a Newbery winner"),
    ("M_100_PAGES", "Read 100 pages in one day"),
    ("M_ALOUD_ALEX", "Read aloud to Alex"),
    ("M_NEW_GENRE", "Try a genre you've never tried"),
    ("M_BEFORE_BREAKFAST", "Read before breakfast"),
    ("M_PAJAMAS", "Stay in pajamas to read all day"),
    ("M_OLDER_BOOK", "Read a book older than you are"),
    ("M_OTHER_COUNTRY", "Book set in another country"),
    ("M_CLASSIC", "Read a classic (Tolkien, Le Guin, etc.)"),
    ("M_FREE", "FREE SPACE"),
    ("M_FRIEND_REC", "A friend's recommendation"),
    ("M_LIBRARY", "Read at the library"),
    ("M_LEVEL_UP", "Read a stretch / level-up book"),
    ("M_60_MIN", "Read 75 pages in one sitting"),
    ("M_POETRY", "Read a collection of poetry"),
    ("M_BIOGRAPHY", "Read a biography"),
    ("M_SCIFI_CLASSIC", "Read a sci-fi classic"),
    ("M_SNACK", "Read with a snack"),
    ("M_SEQUEL", "Read a book and its sequel"),
    ("M_BOOKSTORE", "Visit a bookstore"),
    ("M_3_DAYS", "Finish a book in 3 days"),
    ("M_CAR", "Read on a trip / in the car"),
]

CARDS: dict[str, list[tuple]] = {
    "alex": ALEX_SQUARES,
    "sam": SAM_SQUARES,
}

FREE_SQUARES = {"W_FREE", "M_FREE"}
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
    for i, (sid, _) in enumerate(squares):
        if sid == square_id:
            return i
    return None


def square_label(reader: str, square_id: str, card_num: int = 1) -> str:
    squares = get_card_squares(reader, card_num)
    for sid, label in squares:
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
    for sid, label in squares:
        sl = sid.lower()
        if sl == q_id or sl.split("_", 1)[-1] == q_id:
            return sid, label
    from rapidfuzz import process, fuzz

    # Build candidates: ID (normalised) + display text
    candidates: dict[str, tuple[str, str]] = {}
    for sid, label in squares:
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
    checked_ix = {i for i, (sid, _) in enumerate(squares) if sid in checked_ids}
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
    books_finished_total: int = 0,  # total books finished all summer
) -> list[tuple[str, str]]:
    triggered = []
    # Comic books / easy readers don't count toward page-count milestones
    NON_PROSE = {"graphic_novel", "graphic_novel_telgemeier", "easy_reader", "picture_book"}
    is_prose = book.get("format") not in NON_PROSE
    if reader == "alex":
        if is_prose and daily_pages >= 50:
            triggered.append(("W_50_PAGES", f"Read {daily_pages} pages today"))
        if is_prose and session_pages >= 30:
            triggered.append(("W_45_MIN", f"Read {session_pages} pages in one sitting"))
        if finished and book.get("format") in (
            "chapter_book",
            "early_chapter_book",
            "dense_middle_grade",
            "dense_classic",
        ):
            triggered.append(("W_FINISH_BOOK", f"Finished {book['title']}"))
            if book_total_pages >= 100:
                triggered.append(
                    ("W_100_PAGE_BOOK", f"Finished {book['title']} ({book_total_pages} pages)")
                )
        if finished and book.get("genre") in ("biography", "memoir"):
            triggered.append(("W_REAL_PERSON", f"Finished biography: {book['title']}"))
        if finished and book.get("format") == "nonfiction":
            triggered.append(("W_NONFICTION", f"Finished nonfiction: {book['title']}"))
        if books_finished_this_week >= 3:
            triggered.append(
                ("W_3_BOOKS_WEEK", f"Finished {books_finished_this_week} books this week")
            )
    elif reader == "sam":
        if is_prose and daily_pages >= 100:
            triggered.append(("M_100_PAGES", f"Read {daily_pages} pages today"))
        if is_prose and session_pages >= 75:
            triggered.append(("M_60_MIN", f"Read {session_pages} pages in one sitting"))
        if finished and book.get("classification") == "masterpiece":
            triggered.append(("M_CLASSIC", f"Finished classic: {book['title']}"))
            if book.get("genre") == "scifi":
                triggered.append(("M_SCIFI_CLASSIC", f"Finished sci-fi classic: {book['title']}"))
        if finished and book.get("award") == "newbery":
            triggered.append(("M_NEWBERY", f"Finished Newbery winner: {book['title']}"))
        if finished and book.get("genre") == "biography":
            triggered.append(("M_BIOGRAPHY", f"Finished biography: {book['title']}"))
        if finished and book.get("format") == "nonfiction":
            triggered.append(("M_NONFICTION", f"Finished nonfiction: {book['title']}"))
        if finished and is_prose and book_first_session_date:
            from datetime import date

            try:
                d1 = date.fromisoformat(book_first_session_date)
                d2 = date.fromisoformat(session_date)
                if (d2 - d1).days <= 2:
                    triggered.append(
                        ("M_3_DAYS", f"Finished {book['title']} in {(d2-d1).days+1} days")
                    )
            except Exception:
                pass
    # ── Card 2 auto-detect rules ─────────────────────────────────────────────
    if card_num == 2:
        if reader == "alex":
            if finished and book.get("format") in ("graphic_novel", "graphic_novel_telgemeier"):
                triggered.append(("W2_GRAPHIC_NOVEL", f"Finished graphic novel: {book['title']}"))
            if is_prose and session_pages >= 50:
                triggered.append(("W2_50_PAGES_SIT", f"Read {session_pages} pages in one sitting"))
            if is_prose and daily_pages >= 100:
                triggered.append(("W2_100_PAGES_DAY", f"Read {daily_pages} pages today"))
            if (
                finished
                and book_total_pages >= 150
                and book.get("format")
                in ("chapter_book", "early_chapter_book", "dense_middle_grade", "dense_classic")
            ):
                triggered.append(
                    ("W2_150_PAGE_BOOK", f"Finished {book['title']} ({book_total_pages} pages)")
                )
            if books_finished_this_week >= 3:
                triggered.append(
                    ("W2_3_BOOKS_WEEK", f"Finished {books_finished_this_week} books this week")
                )
            if books_finished_total >= 10:
                triggered.append(
                    ("W2_10_BOOKS", f"Finished {books_finished_total} books this summer")
                )
            if finished and is_prose and book_first_session_date:
                from datetime import date as _date

                try:
                    d1 = _date.fromisoformat(book_first_session_date)
                    d2 = _date.fromisoformat(session_date)
                    if (d2 - d1).days <= 1:
                        triggered.append(
                            ("W2_2_DAYS", f"Finished {book['title']} in {(d2-d1).days+1} days")
                        )
                except Exception:
                    pass
        elif reader == "sam":
            if finished and book.get("format") in ("graphic_novel", "graphic_novel_telgemeier"):
                triggered.append(("M2_GRAPHIC_NOVEL", f"Finished graphic novel: {book['title']}"))
            if is_prose and session_pages >= 100:
                triggered.append(("M2_100_PAGES_SIT", f"Read {session_pages} pages in one sitting"))
            if is_prose and daily_pages >= 200:
                triggered.append(("M2_200_PAGES_DAY", f"Read {daily_pages} pages today"))
            if (
                finished
                and book_total_pages >= 400
                and book.get("format") in ("chapter_book", "dense_middle_grade", "dense_classic")
            ):
                triggered.append(
                    ("M2_400_PAGE_BOOK", f"Finished {book['title']} ({book_total_pages} pages)")
                )
            if finished and book.get("classification") == "masterpiece":
                triggered.append(("M2_CLASSIC_2", f"Finished classic: {book['title']}"))
            if finished and book.get("award") == "newbery":
                triggered.append(("M2_NEWBERY_2", f"Finished Newbery winner: {book['title']}"))
            if finished and book.get("genre") == "biography":
                triggered.append(("M2_BIOGRAPHY_2", f"Finished biography: {book['title']}"))
            if finished and book.get("genre") == "scifi":
                triggered.append(("M2_SCIFI_2", f"Finished sci-fi: {book['title']}"))
            if books_finished_total >= 5:
                triggered.append(
                    ("M2_5_BOOKS", f"Finished {books_finished_total} books this summer")
                )
            if books_finished_total >= 10:
                triggered.append(
                    ("M2_10_BOOKS", f"Finished {books_finished_total} books this summer")
                )
            if finished and is_prose and book_first_session_date:
                from datetime import date as _date

                try:
                    d1 = _date.fromisoformat(book_first_session_date)
                    d2 = _date.fromisoformat(session_date)
                    if (d2 - d1).days <= 1:
                        triggered.append(
                            ("M2_2_DAYS", f"Finished {book['title']} in {(d2-d1).days+1} days")
                        )
                except Exception:
                    pass
    return triggered


# ── Card 2 definitions ────────────────────────────────────────────────────────
# New squares with harder / different challenges. Auto-detectable IDs noted.

ALEX_SQUARES_2 = [
    ("W2_GRAPHIC_NOVEL", "Read a graphic novel"),  # auto: format=graphic_novel
    ("W2_2_DAYS", "Finish a book in 2 days"),  # auto
    ("W2_150_PAGE_BOOK", "Book with 150+ pages"),  # auto
    ("W2_MYSTERY", "Read a mystery book"),  # manual
    ("W2_OUTSIDE_AFTNN", "Read outside for a whole afternoon"),  # manual
    ("W2_ALOUD_KID", "Read aloud to a younger kid"),  # manual
    ("W2_HISTORY", "Book set in the past"),  # manual
    ("W2_ANIMAL_BOOK", "Book with an animal hero"),  # manual
    ("W2_BEFORE_TV", "Read before any TV, 3 days"),  # manual
    ("W2_NEW_SERIES", "Start a brand-new series"),  # manual
    ("W2_FUNNY_BOOK", "A book that made you laugh out loud"),  # manual
    ("W2_50_PAGES_SIT", "Read 50 pages in one sitting"),  # auto
    ("W2_FREE", "FREE SPACE"),
    ("W2_REREAD", "Re-read a favourite book"),  # manual
    ("W2_RECOMMEND", "Recommend a book to a friend"),  # manual
    ("W2_SCARY", "Read something a little scary"),  # manual
    ("W2_MAGIC_BOOK", "Book with magic or fantasy"),  # manual
    ("W2_10_BOOKS", "Finish your 10th book this summer"),  # auto
    ("W2_SERIES_2", "Read 2+ books in the same series"),  # manual (no series metadata)
    ("W2_100_PAGES_DAY", "Read 100 pages in one day"),  # auto
    ("W2_MORNING_3", "Read before breakfast 3 mornings"),  # manual
    ("W2_DIFFERENT_CTRY", "Book set in a different country"),  # manual
    ("W2_POEM_WEEK", "Read a poem every day for a week"),  # manual
    ("W2_3_BOOKS_WEEK", "Read 3 books in one week"),  # auto
    ("W2_BLANKET_FORT", "Build a reading fort and read in it"),  # manual
]

SAM_SQUARES_2 = [
    ("M2_GRAPHIC_NOVEL", "Read a graphic novel or manga"),  # auto
    ("M2_2_DAYS", "Finish a book in 2 days"),  # auto
    ("M2_400_PAGE_BOOK", "Book with 400+ pages"),  # auto
    ("M2_HISTORICAL", "Historical fiction"),  # manual
    ("M2_200_PAGES_DAY", "Read 200 pages in one day"),  # auto
    ("M2_RECOMMEND_W", "Recommend a book to Alex"),  # manual
    ("M2_NEW_GENRE", "Try a genre you've never read"),  # manual
    ("M2_SERIES_3", "Read 3+ books in same series"),  # manual (no series metadata)
    ("M2_BEFORE_SCREENS", "Read before any screens, 3 days"),  # manual
    ("M2_REREAD", "Re-read a favourite book"),  # manual
    ("M2_CLASSIC_2", "Read a second classic"),  # auto: classification=masterpiece
    ("M2_100_PAGES_SIT", "Read 100 pages in one sitting"),  # auto
    ("M2_FREE", "FREE SPACE"),
    ("M2_LIBRARY_2", "Check out 3 books from the library"),  # manual
    ("M2_5_BOOKS", "Finish 5 books"),  # auto
    ("M2_POEM", "Read a poetry collection"),  # manual
    ("M2_BIOGRAPHY_2", "Read a second biography"),  # auto
    ("M2_AUDIOBOOK", "Listen to an audiobook"),  # manual
    ("M2_NEWBERY_2", "Read a second Newbery winner"),  # auto
    ("M2_REVIEW", "Write a book review"),  # manual
    ("M2_MORNING_WEEK", "Read every morning for a week"),  # manual
    ("M2_LONG_SITTING", "Read for 2 hours straight"),  # manual
    ("M2_10_BOOKS", "Finish 10 books"),  # auto
    ("M2_SCIFI_2", "Read a second sci-fi book"),  # auto
    ("M2_BUDDY_READ", "Read the same book as Alex"),  # manual
]

CARDS_BY_NUM: dict[int, dict[str, list]] = {
    1: {"alex": ALEX_SQUARES, "sam": SAM_SQUARES},
    2: {"alex": ALEX_SQUARES_2, "sam": SAM_SQUARES_2},
}

FREE_SQUARES_BY_NUM: dict[int, set] = {
    1: {"W_FREE", "M_FREE"},
    2: {"W2_FREE", "M2_FREE"},
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


def _generated_card(reader: str) -> list[tuple]:
    """Build a default card for a reader, with per-reader-prefixed square IDs."""
    prefix = (reader or "R").upper()
    return [(f"{prefix}_{suffix}", label) for suffix, label in DEFAULT_CARD_TEMPLATE]


def get_card_squares(reader: str, card_num: int) -> list[tuple]:
    """Return the square list for a given reader and card number.

    Readers with a hand-authored card (alex/sam) use it verbatim; any
    other configured reader gets a generated default card so bingo works for
    new readers out of the box. Manual check/uncheck works immediately;
    auto-detection is opt-in per reader and simply no-ops for the rest.
    """
    cards = CARDS_BY_NUM.get(card_num, CARDS_BY_NUM[1])
    if reader in cards:
        return cards[reader]
    return _generated_card(reader)


def get_free_square(reader: str, card_num: int) -> str | None:
    """Return the free square ID for this card."""
    for sq_id, _ in get_card_squares(reader, card_num):
        if "FREE" in sq_id:
            return sq_id
    return None


def line_bonus(card_num: int) -> int:
    """Points awarded per completed bingo line. Doubles each card."""
    return BINGO_LINE_BONUS * (2 ** (card_num - 1))


def total_lines() -> int:
    return len(BINGO_LINES)
