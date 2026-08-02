from datetime import date

from heterscan.normalize import clean_text, in_range, parse_date, record_identity


def test_hebrew_text_normalization() -> None:
    assert clean_text("  פתח\u200f   תקווה ") == "פתח תקווה"


def test_date_parser_handles_municipal_format() -> None:
    assert parse_date("07/04/2024") == date(2024, 4, 7)


def test_range_is_inclusive() -> None:
    assert in_range(date(2024, 1, 31), date(2024, 1, 1), date(2024, 1, 31))


def test_application_number_is_preferred_identity() -> None:
    assert record_identity("7900", "2024-00321", {"address": "א"}) == "application:2024 00321"
