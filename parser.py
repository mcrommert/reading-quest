"""Parse Mattermost slash command text for the reading bot."""
import re

from readers import resolve_reader, READER_KEYS

FORMATS = {
    "chapter":            "chapter_book",
    "chapter_book":       "chapter_book",
    "novel":              "chapter_book",
    "early":              "early_chapter_book",
    "early_chapter":      "early_chapter_book",
    "early_chapter_book": "early_chapter_book",
    "dense":              "dense_middle_grade",
    "dense_middle":       "dense_middle_grade",
    "dense_middle_grade": "dense_middle_grade",
    "dense_classic":      "dense_classic",
    "classic_dense":      "dense_classic",
    "nonfiction":         "nonfiction",
    "nf":                 "nonfiction",
    "graphic":            "graphic_novel",
    "graphic_novel":      "graphic_novel",
    "gn":                 "graphic_novel",
    "easy":               "easy_reader",
    "easy_reader":        "easy_reader",
    "er":                 "easy_reader",
}


def normalize(s: str) -> str:
    """Lowercase, strip punctuation (keep #), collapse spaces."""
    s = s.lower()
    s = re.sub(r"[^\w\s#]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _extract_int(pattern, text):
    """Return (value, text_with_match_removed) or (None, text)."""
    m = re.search(pattern, text, re.I)
    if m:
        return int(m.group(1)), (text[: m.start()] + text[m.end():]).strip()
    return None, text


# Sanity ceiling for a single logged session — guards against typos/abuse
# (e.g. pages=999999999 posting an absurd score).
MAX_PAGES = 2000


def parse_read_command(text: str) -> dict:
    """
    Parse: alex "Junie B Jones 12" pages=25 minutes=30
    Also handles: sam harry potter pages=50 min=45
                  w "dog man" 50p 30m
                  alex "new book" pages=30 minutes=20 format=chapter
                  alex "book" pages=30 date=2026-06-07
                  alex "book" pages=30 date=yesterday
                  alex "book" pages=30 date=saturday

    Returns dict with keys: reader, book_raw, pages, minutes, format_hint, date
    On error: {"error": "..."}
    """
    text = text.strip()
    parts = text.split(None, 1)
    if not parts:
        return {"error": _usage()}

    reader = resolve_reader(parts[0])
    if not reader:
        return {"error": f"Unknown reader **{parts[0]}**. Use one of: {', '.join(READER_KEYS)}."}

    rest = parts[1] if len(parts) > 1 else ""

    # --- Extract date override (date=YYYY-MM-DD, date=yesterday, date=saturday, etc.) ---
    date_val = None
    m = re.search(r'date\s*=\s*(\S+)', rest, re.I)
    if m:
        date_val = m.group(1).lower().rstrip(',')
        rest = (rest[: m.start()] + rest[m.end():]).strip()

    # --- Extract finished flag ---
    finished = False
    m = re.search(r'\b(?:finished?|done|complete[d]?)\s*=?\s*(?:true|yes|1)?\b', rest, re.I)
    if m and ('=' in m.group(0) or any(w in m.group(0).lower() for w in ('true','yes','1'))):
        finished = True
        rest = (rest[: m.start()] + rest[m.end():]).strip()
    elif re.search(r'\bfinished\b|\bdone\b', rest, re.I):
        # bare 'finished' or 'done' at end of string also counts
        m2 = re.search(r'\s*\b(finished|done)\b\s*$', rest, re.I)
        if m2:
            finished = True
            rest = rest[: m2.start()].strip()

    # --- Extract audiobook flag (audiobook / audio / listened) ---
    audiobook = False
    m = re.search(r'\b(?:audiobook|audiobooks|audio|listened)\b', rest, re.I)
    if m:
        audiobook = True
        rest = (rest[: m.start()] + rest[m.end():]).strip()

    # --- Extract format hint (for unknown-book flow) ---
    fmt_hint = None
    m = re.search(r'format\s*=\s*(\w+)', rest, re.I)
    if m:
        fmt_hint = FORMATS.get(m.group(1).lower())
        rest = (rest[: m.start()] + rest[m.end():]).strip()

    # --- Extract pages (pages=N, p=N, Np, N pages) ---
    pages, rest = _extract_int(r'(?:pages?|p)\s*=\s*(\d+)', rest)
    if pages is None:
        pages, rest = _extract_int(r'(\d+)\s*(?:pages?|pg)(?!\w)', rest)
    if pages is None:
        # bare number followed by 'p' not part of a word
        pages, rest = _extract_int(r'\b(\d+)p\b', rest)

    # --- Extract minutes (minutes=N, min=N, Nm, N min) ---
    minutes, rest = _extract_int(r'(?:minutes?|mins?)\s*=\s*(\d+)', rest)
    if minutes is None:
        minutes, rest = _extract_int(r'(\d+)\s*(?:minutes?|mins?)(?!\w)', rest)
    if minutes is None:
        minutes, rest = _extract_int(r'\b(\d+)m\b', rest)

    # --- What remains is the book title ---
    book_raw = rest.strip().strip('"').strip("'").strip()

    # --- Validate ---
    if not book_raw:
        return {"error": _usage()}
    if pages is None:
        return {"error": "Need a page count. Example: `pages=25`"}
    if pages <= 0:
        return {"error": "`pages` must be greater than 0."}
    if pages > MAX_PAGES:
        return {"error": f"`pages` looks too large (max {MAX_PAGES}). Split it into multiple sessions."}
    if minutes is None:
        minutes = 0
    if minutes < 0:
        return {"error": "`minutes` must be 0 or greater."}

    return {
        "reader":      reader,
        "book_raw":    book_raw,
        "pages":       pages,
        "minutes":     minutes,
        "format_hint": fmt_hint,
        "finished":    finished,
        "date":        date_val,
        "audiobook":   audiobook,
    }


def _usage():
    return (
        "Usage: `/read [alex|sam] \"book title\" pages=N`\n"
        "Example: `/read alex \"Junie B Jones 12\" pages=25`"
    )
