"""User-facing strings and calendar colours follow reader config.

These were hardcoded to the sample family. Left alone, a deployment whose
children are not called Alex and Sam would tell them to type someone else's
name, and would drop every calendar event to the default colour.
"""

import gcal
import parser as parser_mod
import readers


class TestHelpText:
    def test_usage_names_the_configured_readers(self):
        usage = parser_mod._usage()
        for key in readers.READER_KEYS:
            assert key in usage, f"{key} missing from usage text"

    def test_usage_does_not_hardcode_the_sample_family(self, monkeypatch):
        monkeypatch.setattr(readers, "READER_KEYS", ["kim", "robin"], raising=False)
        monkeypatch.setattr(parser_mod, "READER_KEYS", ["kim", "robin"], raising=False)
        usage = parser_mod._usage()
        assert "kim" in usage and "robin" in usage
        assert "alex" not in usage.lower() and "sam" not in usage.lower()

    def test_example_uses_a_real_configured_reader(self, monkeypatch):
        monkeypatch.setattr(parser_mod, "READER_KEYS", ["kim", "robin"], raising=False)
        assert "Example: `/read kim" in parser_mod._usage()

    def test_no_readers_configured_does_not_crash(self, monkeypatch):
        monkeypatch.setattr(parser_mod, "READER_KEYS", [], raising=False)
        assert "reader" in parser_mod._usage()


class TestCalendarColours:
    def test_each_configured_reader_gets_a_distinct_colour(self):
        colours = [gcal._reader_color(k) for k in readers.READER_KEYS]
        assert len(set(colours)) == len(colours), "two readers share a calendar colour"
        assert "0" not in colours, "a configured reader fell back to the default colour"

    def test_colour_follows_roster_position_not_name(self, monkeypatch):
        """The point of the change: any family's readers get colour-coded."""
        monkeypatch.setattr(gcal, "READER_KEYS", ["kim", "robin"], raising=False)
        assert gcal._reader_color("kim") == gcal._READER_COLORS[0]
        assert gcal._reader_color("robin") == gcal._READER_COLORS[1]

    def test_unknown_reader_falls_back_to_calendar_default(self, monkeypatch):
        monkeypatch.setattr(gcal, "READER_KEYS", ["kim"], raising=False)
        assert gcal._reader_color("stranger") == "0"

    def test_more_readers_than_colours_wraps_rather_than_crashing(self, monkeypatch):
        many = [f"r{i}" for i in range(len(gcal._READER_COLORS) + 3)]
        monkeypatch.setattr(gcal, "READER_KEYS", many, raising=False)
        for key in many:
            assert gcal._reader_color(key) in gcal._READER_COLORS

    def test_family_colour_is_separate_from_every_reader(self):
        assert gcal._COLOR_FAMILY not in gcal._READER_COLORS
