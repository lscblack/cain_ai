"""Case-code generation: CASE-YYYY-NNNN."""
from __future__ import annotations


def generate_case_code(year: int, sequence: int) -> str:
    """sequence is 1-based within the year."""
    return f"CASE-{year:04d}-{sequence:04d}"


def next_sequence(latest_code: str | None, year: int) -> int:
    """Given the latest existing code (or None) and the current year, return the
    next 1-based sequence number for that year."""
    if not latest_code:
        return 1
    try:
        _, code_year, seq = latest_code.split("-")
        if int(code_year) != year:
            return 1
        return int(seq) + 1
    except (ValueError, AttributeError):
        return 1
