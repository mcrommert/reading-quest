"""Auto-detection triggers.

Trigger rules used to be `if reader == "alex"` branches in auto_detect. They now
live on the squares themselves as metric+comparator specs, so a card carries its
own rules wherever it is defined — including a card written in a family's own
config. These tests pin the thresholds so that move didn't change what earns a
square.
"""

import pytest

import bingo


def book(**over):
    b = {"title": "Some Book", "format": "chapter_book", "classification": "standard"}
    b.update(over)
    return b


def detect(reader="alex", card_num=1, **over):
    kwargs = dict(
        reader=reader,
        session_pages=0,
        session_minutes=0,
        daily_pages=0,
        book=book(),
        finished=False,
        book_first_session_date=None,
        session_date="2026-07-10",
        books_finished_this_week=0,
        book_total_pages=0,
        card_num=card_num,
        books_finished_total=0,
    )
    kwargs.update(over)
    return dict(bingo.auto_detect(**kwargs))


class TestPageThresholds:
    def test_daily_page_square_fires_exactly_at_the_threshold(self):
        assert "W_50_PAGES" not in detect(daily_pages=49)
        assert "W_50_PAGES" in detect(daily_pages=50)

    def test_sitting_square_fires_exactly_at_the_threshold(self):
        assert "W_45_MIN" not in detect(session_pages=29)
        assert "W_45_MIN" in detect(session_pages=30)

    def test_thresholds_differ_per_card_set(self):
        """The older card demands more pages for the equivalent square."""
        assert "M_100_PAGES" not in detect(reader="sam", daily_pages=99)
        assert "M_100_PAGES" in detect(reader="sam", daily_pages=100)

    @pytest.mark.parametrize(
        "fmt", ["graphic_novel", "graphic_novel_telgemeier", "easy_reader", "picture_book"]
    )
    def test_illustrated_formats_never_count_toward_page_milestones(self, fmt):
        """A 200-page comic is not 200 pages of reading."""
        fired = detect(daily_pages=200, session_pages=200, book=book(format=fmt))
        assert "W_50_PAGES" not in fired
        assert "W_45_MIN" not in fired

    def test_page_squares_do_not_require_finishing(self):
        assert "W_50_PAGES" in detect(daily_pages=50, finished=False)


class TestFinishConditions:
    def test_finishing_a_prose_book_checks_the_finish_square(self):
        assert "W_FINISH_BOOK" in detect(finished=True)

    def test_not_finishing_checks_nothing(self):
        assert "W_FINISH_BOOK" not in detect(finished=False)

    def test_finishing_a_comic_does_not_count_as_finishing_a_book(self):
        assert "W_FINISH_BOOK" not in detect(finished=True, book=book(format="graphic_novel"))

    def test_page_count_square_needs_both_finish_and_length(self):
        assert "W_100_PAGE_BOOK" not in detect(finished=True, book_total_pages=99)
        assert "W_100_PAGE_BOOK" not in detect(finished=False, book_total_pages=250)
        assert "W_100_PAGE_BOOK" in detect(finished=True, book_total_pages=100)

    def test_classification_and_genre_can_both_be_required(self):
        """M_SCIFI_CLASSIC needs a masterpiece AND scifi; M_CLASSIC needs only the first."""
        classic = detect(reader="sam", finished=True, book=book(classification="masterpiece"))
        assert "M_CLASSIC" in classic and "M_SCIFI_CLASSIC" not in classic

        scifi = detect(
            reader="sam", finished=True, book=book(classification="masterpiece", genre="scifi")
        )
        assert "M_CLASSIC" in scifi and "M_SCIFI_CLASSIC" in scifi

    def test_award_condition(self):
        assert "M_NEWBERY" in detect(reader="sam", finished=True, book=book(award="newbery"))
        assert "M_NEWBERY" not in detect(reader="sam", finished=True, book=book(award="carnegie"))

    def test_a_genre_list_matches_any_member(self):
        for genre in ("biography", "memoir"):
            assert "W_REAL_PERSON" in detect(finished=True, book=book(genre=genre))
        assert "W_REAL_PERSON" not in detect(finished=True, book=book(genre="fantasy"))


class TestDaysToFinish:
    def test_counts_days_inclusively(self):
        """Started and finished the same day is one day, not zero."""
        fired = detect(
            reader="sam",
            finished=True,
            book_first_session_date="2026-07-10",
            session_date="2026-07-10",
        )
        assert "M_3_DAYS" in fired
        assert "in 1 days" in fired["M_3_DAYS"]

    def test_fires_up_to_and_including_the_limit(self):
        def days(n):
            return detect(
                reader="sam",
                finished=True,
                book_first_session_date="2026-07-10",
                session_date=f"2026-07-{9 + n:02d}",
            )

        assert "M_3_DAYS" in days(3)
        assert "M_3_DAYS" not in days(4)

    def test_requires_finishing(self):
        assert "M_3_DAYS" not in detect(
            reader="sam",
            finished=False,
            book_first_session_date="2026-07-10",
            session_date="2026-07-10",
        )

    def test_missing_or_malformed_start_date_is_not_a_crash(self):
        for bad in (None, "", "not-a-date"):
            assert "M_3_DAYS" not in detect(
                reader="sam",
                finished=True,
                book_first_session_date=bad,
                session_date="2026-07-10",
            )


class TestReasons:
    def test_reason_interpolates_the_measured_value(self):
        assert detect(daily_pages=73)["W_50_PAGES"] == "Read 73 pages today"

    def test_reason_interpolates_the_book_title(self):
        fired = detect(finished=True, book=book(title="Hatchet"))
        assert fired["W_FINISH_BOOK"] == "Finished Hatchet"

    def test_reason_can_combine_values(self):
        fired = detect(finished=True, book_total_pages=210, book=book(title="Hatchet"))
        assert fired["W_100_PAGE_BOOK"] == "Finished Hatchet (210 pages)"


class TestCardScoping:
    def test_only_the_current_card_is_evaluated(self):
        """Behaviour change, deliberate: rules used to be evaluated for card 1 even
        while the reader was on card 2, writing state for squares that were not on
        their grid. Triggers now travel with the card, so only its own squares fire."""
        on_card_2 = detect(card_num=2, daily_pages=200, session_pages=200)
        assert "W_50_PAGES" not in on_card_2
        assert "W2_100_PAGES_DAY" in on_card_2

    def test_card_two_thresholds_are_harder(self):
        assert "W2_100_PAGES_DAY" not in detect(card_num=2, daily_pages=99)
        assert "W2_100_PAGES_DAY" in detect(card_num=2, daily_pages=100)

    def test_a_generated_card_has_no_triggers_and_does_not_crash(self, monkeypatch):
        """A newly added reader gets a manual-only card. Bingo still works; nothing
        auto-checks until someone authors rules for them."""
        import readers

        monkeypatch.setattr(readers, "READERS_BY_KEY", {"kim": {"key": "kim"}}, raising=False)
        assert detect(reader="kim", daily_pages=500, finished=True) == {}


class TestTriggerEngine:
    def test_all_conditions_must_hold(self):
        ctx = {"daily_pages": 100, "is_prose": False, "finished": False}
        squares = [("X", "x", {"daily_pages": {"gte": 50}, "prose_only": True})]
        assert bingo.evaluate_triggers(squares, ctx) == []

    def test_squares_without_triggers_are_manual_only(self):
        ctx = {"daily_pages": 100, "is_prose": True, "finished": False}
        assert bingo.evaluate_triggers([("X", "x"), ("Y", "y", None)], ctx) == []

    def test_an_unknown_condition_is_an_error_not_a_silent_pass(self):
        """A typo in a config-authored trigger must not quietly award the square."""
        ctx = {"daily_pages": 100, "is_prose": True, "finished": False}
        with pytest.raises(ValueError, match="unknown trigger condition"):
            bingo.evaluate_triggers([("X", "x", {"daly_pages": {"gte": 1}})], ctx)

    def test_every_shipped_trigger_uses_a_known_condition(self):
        """Guards the shipped cards against the same typo."""
        ctx = {
            "daily_pages": 0,
            "session_pages": 0,
            "book_total_pages": 0,
            "books_finished_week": 0,
            "books_finished_total": 0,
            "days_to_finish": None,
            "finished": False,
            "is_prose": True,
            "format": None,
            "genre": None,
            "classification": None,
            "award": None,
            "title": "t",
        }
        for name, cards in bingo.CARD_SETS.items():
            for num, squares in cards.items():
                bingo.evaluate_triggers(squares, ctx)  # raises on an unknown condition
