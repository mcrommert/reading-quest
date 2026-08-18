"""Catalog integrity.

books.json is the largest hand-maintained thing in the repo — thousands of
entries, edited in bulk imports. Scoring reads it with `.get(..., default)`
throughout, so a bad value doesn't raise; it silently scores as the default.
These checks make that visible instead.
"""

import pytest

import scoring


def test_every_book_has_a_key_and_title(catalog):
    for key, b in catalog.items():
        assert b.get("key") == key
        assert b.get("title"), f"{key} has no title"


def test_no_duplicate_keys(catalog):
    """The catalog is a list; a duplicate key means one entry silently wins."""
    import json
    from pathlib import Path

    raw = json.loads(
        (Path(__file__).resolve().parent.parent / "books.json").read_text(encoding="utf-8")
    )
    keys = [b["key"] for b in raw]
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"duplicate book keys: {sorted(dupes)[:10]}"


def test_every_classification_is_recognised(catalog):
    """CLASSIC_BONUS.get(x, 0.0) means an unrecognised value scores as standard
    without complaint. 54 entries were tagged 'fiction' this way — harmless only
    because standard happens to be the right answer for them."""
    valid = set(scoring.CLASSIC_BONUS)
    bad = {
        k: b["classification"]
        for k, b in catalog.items()
        if b.get("classification") and b["classification"] not in valid
    }
    assert not bad, f"unrecognised classifications: {sorted(set(bad.values()))} in {len(bad)} books"


def test_every_format_is_recognised(catalog):
    """An unrecognised format falls through to density 1.0, quietly under-scoring
    a dense book."""
    valid = set(scoring.DENSITY_BY_FORMAT) | set(scoring.SPECIAL_OVERRIDES)
    bad = {
        k: b["format"] for k, b in catalog.items() if b.get("format") and b["format"] not in valid
    }
    assert not bad, f"unrecognised formats: {sorted(set(bad.values()))} in {len(bad)} books"


def test_level_keyed_overrides_name_real_levels(catalog):
    """An override under a misspelled level silently never applies."""
    import readers

    valid = set(readers.LEVELS)
    bad = {}
    for key, b in catalog.items():
        for level in b.get("ppp_override_by_level", {}):
            if level not in valid:
                bad[key] = level
    assert not bad, f"overrides on unknown levels: {bad}"


def test_lexiles_are_plausible(catalog):
    """A negative or absurd Lexile would land every reader in the wrong tier."""
    bad = {
        k: b["lexile"]
        for k, b in catalog.items()
        if b.get("lexile") is not None and not (0 <= b["lexile"] <= 2000)
    }
    assert not bad, f"implausible Lexile values: {bad}"


def test_every_book_scores_without_raising(catalog):
    """Whole-catalog smoke: no entry may blow up the scorer for any reader."""
    for key, b in catalog.items():
        for reader in ("alex", "sam"):
            result = scoring.compute_points(b, reader, 50)
            assert result["ppp"] >= 0, f"{key} scored negative for {reader}"
