"""Scoring parity against the pre-refactor production implementation.

Every case here is a real logged reading session (or, for the handful marked
`synthetic`, a real book scored through the same frozen code) replayed through
the original scorer, with its output recorded verbatim. If a refactor changes
any of these numbers it changes what a child's reading is worth, which is the
one regression that is completely invisible on the board — wrong points look
exactly like right points.

This suite is the cutover gate. It must stay green.
"""

import pytest

import scoring


def _case_id(case):
    tag = "synth" if case.get("synthetic") else "real"
    audio = "+audio" if case["audiobook"] else ""
    return f"{tag}-{case['reader']}-{case['book_key'][:34]}-{case['pages']}p{audio}"


def test_fixture_is_present_and_broad(parity_cases, catalog):
    """Guard the guard: a truncated fixture would pass vacuously."""
    assert len(parity_cases) >= 90, "parity fixture looks truncated"
    assert {c["reader"] for c in parity_cases} == {"alex", "sam"}
    # Every scoring path must be represented, or parity proves less than it looks.
    tiers = {c["expected"]["tier"] for c in parity_cases}
    for required in (
        "way_below",
        "easy",
        "comfort",
        "stretch",
        "big_stretch",
        "override",
        "graphic_novel",
        "easy_reader",
        "picture_book",
    ):
        assert required in tiers, f"no case exercises the {required!r} path"
    assert any(c["audiobook"] for c in parity_cases), "no audiobook case"
    # Each case carries its own book snapshot, so parity never depends on
    # books.json. The catalog is expected to change; scoring is not.
    assert all("book" in c for c in parity_cases), "case missing its book snapshot"


def test_reader_levels_match_the_captured_roster(parity_cases):
    """The fixture records each reader's level; scoring must agree.

    If this fails, the parity results below are meaningless — they would be
    comparing against a reader scored on a different ladder.
    """
    import readers

    for case in parity_cases:
        assert readers.level_for(case["reader"]) == case["level"]


def test_scoring_parity(parity_cases):
    """Replay every captured case and diff against the recorded output.

    Uses the book snapshot embedded in each case rather than books.json, so a
    catalog edit can never turn this gate red on its own.
    """
    failures = []
    for case in parity_cases:
        book = case["book"]
        got = scoring.compute_points(
            book, case["reader"], case["pages"], audiobook=case["audiobook"]
        )
        exp = case["expected"]
        if (
            round(got["ppp"], 4) != round(exp["ppp"], 4)
            or round(got["points"], 4) != round(exp["points"], 4)
            or got["tier"] != exp["tier"]
        ):
            failures.append(
                f"{_case_id(case)}: expected ppp={exp['ppp']} points={exp['points']} "
                f"tier={exp['tier']} -> got ppp={got['ppp']} points={got['points']} "
                f"tier={got['tier']}"
            )
    assert not failures, "scoring drifted from the captured baseline:\n  " + "\n  ".join(failures)


def test_audiobook_quarters_the_points(catalog):
    """The ×0.25 rule, stated explicitly rather than only implied by parity."""
    book = next(b for b in catalog.values() if b.get("format") == "chapter_book")
    full = scoring.compute_points(book, "alex", 100, audiobook=False)
    audio = scoring.compute_points(book, "alex", 100, audiobook=True)
    assert audio["ppp"] == round(full["ppp"] * scoring.AUDIOBOOK_FACTOR, 2)
    assert audio["points"] == round(full["points"] * scoring.AUDIOBOOK_FACTOR, 2)
    assert audio["full_ppp"] == full["ppp"]
    assert full["audiobook"] is False and audio["audiobook"] is True


def test_per_book_override_beats_every_other_path(catalog):
    """A `{reader}_ppp_override` bypasses tiers, bonus and density entirely."""
    key = next(k for k, b in catalog.items() if "alex_ppp_override" in b)
    book = catalog[key]
    got = scoring.compute_points(book, "alex", 100, audiobook=False)
    assert got["tier"] == "override"
    assert got["ppp"] == float(book["alex_ppp_override"])
    assert got["points"] == 100 * float(book["alex_ppp_override"])


def test_special_formats_resolve_by_level_not_reader_name(catalog):
    """Illustrated formats are keyed by reading level, so any reader works.

    This is the property that lets a new reader be added as pure config — the
    thing the whole N-reader refactor rests on.
    """
    book = next(
        b
        for b in catalog.values()
        if b.get("format") == "graphic_novel" and "alex_ppp_override" not in b
    )
    alex = scoring.compute_points(book, "alex", 100)
    sam = scoring.compute_points(book, "sam", 100)
    assert alex["ppp"] == scoring.SPECIAL_OVERRIDES["graphic_novel"]["developing"]
    assert sam["ppp"] == scoring.SPECIAL_OVERRIDES["graphic_novel"]["capable"]
    # Lower-level readers get more credit for illustrated books, not less.
    assert alex["ppp"] > sam["ppp"]


@pytest.mark.parametrize(
    "lexile,expected",
    [(150, "way_below"), (250, "easy"), (400, "comfort"), (550, "stretch"), (900, "big_stretch")],
)
def test_tier_boundaries_for_developing(lexile, expected):
    """Ladder boundaries pinned explicitly — parity alone wouldn't catch an
    off-by-one at a boundary no logged session happens to sit on."""
    name, _ = scoring.get_tier(lexile, "alex")
    assert name == expected


@pytest.mark.parametrize(
    "lexile,expected",
    [
        (550, "way_below"),
        (700, "easy"),
        (1000, "comfort"),
        (1200, "stretch"),
        (1400, "big_stretch"),
    ],
)
def test_tier_boundaries_for_capable(lexile, expected):
    name, _ = scoring.get_tier(lexile, "sam")
    assert name == expected
