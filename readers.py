"""Reader + reading-level configuration.

This is the single source of truth for *who* reads and *at what level*. Scoring,
bingo, and the board all read from here so adding a kid is a config edit, not a
code change. (Eventually this can move to a config.yaml; a plain module keeps it
dependency-free for now.)

A "reading level" is a Lexile tier ladder — the boundaries that decide how a
book scores for that reader (way_below → big_stretch). Define levels once; each
reader points at one by key. Two readers can share a level.
"""

# ---------------------------------------------------------------------------
# Reading levels — Lexile tier ladders.
# Each entry: (upper_exclusive_boundary, tier_name, ppp_tier_value)
# A book's Lexile falls into the first tier whose boundary it is under; the
# final (None, ...) tier catches everything at/above the last boundary.
#
# These are sensible defaults by grade band; tune the boundaries freely.
# Two readers can share a level.
# ---------------------------------------------------------------------------
LEVELS = {
    "emerging": [   # ~PreK–K, just starting to decode
        (100,  "way_below",   0.25),
        (200,  "easy",        0.50),
        (300,  "comfort",     1.00),
        (450,  "stretch",     1.50),
        (None, "big_stretch", 2.00),
    ],
    "beginning": [  # ~1st grade
        (150,  "way_below",   0.25),
        (250,  "easy",        0.50),
        (380,  "comfort",     1.00),
        (520,  "stretch",     1.50),
        (None, "big_stretch", 2.00),
    ],
    "developing": [  # ~2nd grade
        (200,  "way_below",   0.25),
        (300,  "easy",        0.50),
        (450,  "comfort",     1.00),
        (600,  "stretch",     1.50),
        (None, "big_stretch", 2.00),
    ],
    "growing": [    # ~3rd grade
        (300,  "way_below",   0.25),
        (450,  "easy",        0.50),
        (650,  "comfort",     1.00),
        (850,  "stretch",     1.50),
        (None, "big_stretch", 2.00),
    ],
    "fluent": [     # ~4th–5th grade
        (450,  "way_below",   0.25),
        (650,  "easy",        0.50),
        (900,  "comfort",     1.00),
        (1100, "stretch",     1.50),
        (None, "big_stretch", 2.00),
    ],
    "capable": [    # ~5th–6th grade
        (600,  "way_below",   0.25),
        (800,  "easy",        0.50),
        (1100, "comfort",     1.00),
        (1300, "stretch",     1.50),
        (None, "big_stretch", 2.00),
    ],
    "advanced": [   # ~7th–8th / early HS
        (800,  "way_below",   0.25),
        (1000, "easy",        0.50),
        (1300, "comfort",     1.00),
        (1500, "stretch",     1.50),
        (None, "big_stretch", 2.00),
    ],
}

DEFAULT_LEVEL = "developing"

# ---------------------------------------------------------------------------
# Readers. Add a boy here (key + a level) and the whole app picks him up.
# ---------------------------------------------------------------------------

# Readers load from your private reader_config.py if present, else the
# shipped sample (reader_config_example.py). See that file for the schema.
# Add a reader there (a key + a level) and the whole app picks them up.
try:
    from reader_config import READERS            # your real family (gitignored)
except ImportError:                              # pragma: no cover
    from reader_config_example import READERS    # shipped sample

READERS_BY_KEY = {r["key"]: r for r in READERS}
READER_KEYS = [r["key"] for r in READERS]

# Input resolution: a user may type a reader's key, name, or any configured
# alias (case-insensitive). Built once from the config above.
ALIAS_TO_KEY = {}
for _r in READERS:
    for _form in {_r["key"], _r["name"], *_r.get("aliases", [])}:
        ALIAS_TO_KEY[_form.lower()] = _r["key"]


def resolve_reader(text):
    """Map a typed key/name/alias to a reader key, or None if unrecognized."""
    return ALIAS_TO_KEY.get((text or "").strip().lower())


def get_reader(reader_key):
    """Return the reader config dict, or None."""
    return READERS_BY_KEY.get((reader_key or "").lower())


def level_for(reader_key):
    """Return a reader's configured level name (falls back to DEFAULT_LEVEL)."""
    r = READERS_BY_KEY.get((reader_key or "").lower())
    return (r or {}).get("level", DEFAULT_LEVEL)


def tier_table_for(reader_key):
    """Return the Lexile tier ladder for a reader (falls back to DEFAULT_LEVEL)."""
    return LEVELS.get(level_for(reader_key), LEVELS[DEFAULT_LEVEL])
