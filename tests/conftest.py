"""Shared test fixtures.

Two things every test here depends on:

1. The repo root on sys.path, so `import scoring` works without installing
   the app as a package.
2. A **pinned reader roster**. readers.py loads READERS from reader_config.py if
   it exists and falls back to reader_config_example.py otherwise — so scoring
   behaviour would otherwise depend on a gitignored file that differs between a
   contributor's machine and CI. Tests pin their own roster instead, which keeps
   results identical everywhere and lets a test exercise a level no configured
   reader happens to use.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures"

# The roster the parity fixture was captured against: two readers, one on each
# of the two levels that reproduce the original hand-tuned tier tables.
TEST_READERS = [
    {"key": "alex", "name": "Alex", "monogram": "A", "age": 7,
     "grade": "2nd grade", "level": "developing", "aliases": ["a"]},
    {"key": "sam", "name": "Sam", "monogram": "S", "age": 10,
     "grade": "5th grade", "level": "capable", "aliases": ["s"],
     "warn_upper_grade": True},
]


@pytest.fixture(autouse=True)
def pinned_readers(monkeypatch):
    """Force the reader roster for every test, whatever reader_config.py says."""
    import readers

    by_key = {r["key"]: r for r in TEST_READERS}
    alias_to_key = {}
    for r in TEST_READERS:
        for form in {r["key"], r["name"], *r.get("aliases", [])}:
            alias_to_key[form.lower()] = r["key"]

    monkeypatch.setattr(readers, "READERS", TEST_READERS, raising=False)
    monkeypatch.setattr(readers, "READERS_BY_KEY", by_key, raising=False)
    monkeypatch.setattr(readers, "READER_KEYS", [r["key"] for r in TEST_READERS], raising=False)
    monkeypatch.setattr(readers, "ALIAS_TO_KEY", alias_to_key, raising=False)
    return TEST_READERS


@pytest.fixture(scope="session")
def catalog():
    """books.json indexed by key."""
    books = json.loads((ROOT / "books.json").read_text(encoding="utf-8"))
    return {b["key"]: b for b in books}


@pytest.fixture(scope="session")
def parity_cases():
    """Golden scoring outputs captured from the pre-refactor production code.

    See tests/fixtures/README.md for how this was produced and why the readers
    are the sample family rather than the real one.
    """
    data = json.loads((FIXTURES / "scoring_parity.json").read_text(encoding="utf-8"))
    return data["cases"]
