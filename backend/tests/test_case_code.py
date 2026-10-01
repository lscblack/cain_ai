from app.intelligence.code import generate_case_code, next_sequence


def test_generate_case_code_padding():
    assert generate_case_code(2026, 1) == "CASE-2026-0001"
    assert generate_case_code(2026, 42) == "CASE-2026-0042"
    assert generate_case_code(2026, 1234) == "CASE-2026-1234"


def test_next_sequence_first_of_year():
    assert next_sequence(None, 2026) == 1


def test_next_sequence_increments_same_year():
    assert next_sequence("CASE-2026-0007", 2026) == 8


def test_next_sequence_resets_on_year_rollover():
    assert next_sequence("CASE-2025-0099", 2026) == 1


def test_next_sequence_handles_garbage():
    assert next_sequence("not-a-code", 2026) == 1
