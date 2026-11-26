"""find_book fuzzy matching: a short alias must not beat the real title.

token_set_ratio scores an alias whose words are all in the query as 100, so
"fight for truth" used to tie between LionBoy's one-word alias "truth" and
"The Fight for Truth", and catalog order picked LionBoy.
"""

import pytest

import app as app_module

CATALOG = [
    {"key": "lionboy-the-truth", "title": "LionBoy: The Truth", "aliases": ["truth", "the truth"]},
    {
        "key": "sw-jedi-apprentice-the-fight-for-truth",
        "title": "Star Wars (Jedi Apprentice): The Fight for Truth",
        "aliases": ["the fight for truth", "jedi apprentice the fight for truth"],
    },
    {"key": "sojourner-truth", "title": "Sojourner Truth", "aliases": []},
]


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr(app_module, "_all_books", lambda: CATALOG)


@pytest.mark.parametrize(
    "query, key",
    [
        ("fight for truth", "sw-jedi-apprentice-the-fight-for-truth"),
        ("jedi apprentice fight for truth", "sw-jedi-apprentice-the-fight-for-truth"),
        ("the fight for truth", "sw-jedi-apprentice-the-fight-for-truth"),
        ("lionboy the truth", "lionboy-the-truth"),
        ("truth", "lionboy-the-truth"),
        ("sojourner truth", "sojourner-truth"),
    ],
)
def test_closest_alias_wins_a_tie(catalog, query, key):
    book, score = app_module.find_book(query)
    assert book["key"] == key
    assert score >= 72


def test_no_match_below_cutoff(catalog):
    assert app_module.find_book("captain underpants") == (None, 0)
