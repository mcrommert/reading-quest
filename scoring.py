"""Pure scoring functions — no I/O, fully testable."""

# Reader reading-levels (Lexile tier ladders) live in readers.py so adding a
# reader is a config edit. get_tier() resolves a reader's ladder from there;
# "developing" / "capable" reproduce the old ALEX_TIERS / SAM_TIERS.
from readers import tier_table_for, level_for, DEFAULT_LEVEL

CLASSIC_BONUS = {
    "masterpiece":    0.50,
    "modern_classic": 0.25,
    "standard":       0.00,
}

TIER_LABELS = {
    "way_below":   "way below level",
    "easy":        "easy",
    "comfort":     "comfort",
    "stretch":     "stretch",
    "big_stretch": "big stretch",
}

# Special format overrides — bypass tier+bonus+density entirely.
# Keyed by reading LEVEL (not reader) so any number of readers works: a reader
# gets the value for their configured level. Illustrated formats are worth more
# to younger/lower-level readers and taper to ~nothing for advanced ones.
# (developing / capable reproduce the original two-reader values exactly.)
SPECIAL_OVERRIDES = {
    "graphic_novel":            {"emerging": 0.25, "beginning": 0.22, "developing": 0.20,
                                 "growing": 0.12, "fluent": 0.08, "capable": 0.05, "advanced": 0.05},
    "graphic_novel_telgemeier": {"emerging": 0.30, "beginning": 0.28, "developing": 0.25,
                                 "growing": 0.15, "fluent": 0.08, "capable": 0.05, "advanced": 0.05},
    "easy_reader":              {"emerging": 0.60, "beginning": 0.55, "developing": 0.50,
                                 "growing": 0.25, "fluent": 0.10, "capable": 0.05, "advanced": 0.05},
    "picture_book":             {"emerging": 0.30, "beginning": 0.28, "developing": 0.25,
                                 "growing": 0.15, "fluent": 0.08, "capable": 0.05, "advanced": 0.05},
}

# Density factor by format (words-per-page proxy)
# early_chapter_book keeps points at today's baseline.
# chapter_book, dense_* earn more to reflect higher reading effort per page.
DENSITY_BY_FORMAT = {
    "early_chapter_book": 1.0,   # Junie B, Magic Tree House, Mercy Watson, Owl Diaries
    "chapter_book":       1.3,   # HP, Wings of Fire, Percy Jackson, Wonder
    "dense_middle_grade": 1.7,   # Redwall, Watership Down, Hobbit, Hatchet
    "dense_classic":      2.0,   # LOTR, Wind in the Willows, Treasure Island
    "nonfiction":         1.1,   # Nonfiction chapter books
}


def get_tier(lexile: int, reader: str) -> tuple:
    """Returns (tier_name, tier_value) for a given lexile + reader.

    The reader's tier ladder comes from their configured reading level
    (readers.py); unknown readers fall back to the default level.
    """
    for boundary, name, value in tier_table_for(reader):
        if boundary is None or lexile < boundary:
            return name, value
    return "big_stretch", 2.00


def get_density(book: dict) -> float:
    """Density factor: per-book override → format default → 1.0.
    Special-override formats (graphic, easy) always return 1.0 (density
    is irrelevant because they bypass the tier system entirely)."""
    fmt = book.get("format", "chapter_book")
    if fmt in SPECIAL_OVERRIDES:
        return 1.0
    d = book.get("density_factor")
    if d is not None:
        return float(d)
    return DENSITY_BY_FORMAT.get(fmt, 1.0)


# Audiobooks earn a fraction of normal points (listening, not reading).
AUDIOBOOK_FACTOR = 0.25


def compute_points(book: dict, reader: str, pages: int, audiobook: bool = False) -> dict:
    """Returns full scoring breakdown dict.

    If audiobook is True, the final ppp and points are scaled by
    AUDIOBOOK_FACTOR (¼) — page/minute stats elsewhere are unaffected.
    """
    fmt = book.get("format", "chapter_book")

    # Per-reader explicit ppp override (bypasses tiers and density)
    override = book.get(f"{reader}_ppp_override")
    if override is not None:
        ppp = float(override)
        result = {
            "ppp": ppp, "points": pages * ppp,
            "tier": "override", "tier_val": None, "bonus": None,
            "density": 1.0, "lexile": book.get("lexile"), "format": fmt,
        }

    # Special format override (graphic novel, easy reader)
    elif fmt in SPECIAL_OVERRIDES:
        _by_level = SPECIAL_OVERRIDES[fmt]
        ppp = _by_level.get(level_for(reader), _by_level[DEFAULT_LEVEL])
        result = {
            "ppp": ppp, "points": pages * ppp,
            "tier": fmt, "tier_val": None, "bonus": None,
            "density": 1.0, "lexile": None, "format": fmt,
        }

    else:
        # Standard chapter-style: tier + classic bonus × density
        lexile              = book.get("lexile") or 0
        tier_name, tier_val = get_tier(lexile, reader)
        classification      = book.get("classification", "standard")
        bonus               = CLASSIC_BONUS.get(classification, 0.0)
        density             = get_density(book)
        ppp                 = round((tier_val + bonus) * density, 2)
        result = {
            "ppp":      ppp,
            "points":   pages * ppp,
            "tier":     tier_name,
            "tier_val": tier_val,
            "bonus":    bonus,
            "density":  density,
            "lexile":   lexile,
            "format":   fmt,
        }

    result["audiobook"] = bool(audiobook)
    if audiobook:
        result["full_ppp"] = result["ppp"]
        result["ppp"]    = round(result["ppp"] * AUDIOBOOK_FACTOR, 2)
        result["points"] = round(result["points"] * AUDIOBOOK_FACTOR, 2)
    return result
