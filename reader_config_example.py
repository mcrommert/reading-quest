"""Example reader configuration — copy to reader_config.py and edit.

    cp reader_config_example.py reader_config.py

reader_config.py is gitignored, so your family's real names / ages / levels
never get committed. If it is absent, the app falls back to these sample
readers so a fresh clone runs out of the box.

Each reader:
  key        short lowercase id used in commands + storage (no spaces)
  name       display name
  monogram   1-2 letters for the board avatar
  age, grade cosmetic, shown on the board
  level      which ladder in readers.LEVELS scores this reader's books
  aliases    extra words that resolve to this reader (case-insensitive)
  warn_upper_grade  (optional) flag UG / 9+ books for a parent preview
"""

READERS = [
    {"key": "alex", "name": "Alex", "monogram": "A", "age": 7,  "grade": "2nd grade", "level": "developing", "aliases": ["a"]},
    {"key": "sam",  "name": "Sam",  "monogram": "S", "age": 10, "grade": "5th grade", "level": "capable",    "aliases": ["s"], "warn_upper_grade": True},
]
