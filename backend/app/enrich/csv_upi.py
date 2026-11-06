"""Parse an uploaded UPI (land-parcel transaction) CSV.

Expected header (case-insensitive, extra columns ignored):
    provincename, districtname, sectorname, cellname, village, upi, size,
    land_use_name_kinyarwanda, transaction_type_name, sale_price, start_date, Year
"""
from __future__ import annotations

import csv
import io

# canonical field -> accepted header names (lowercased)
_FIELD_ALIASES = {
    "province": ("provincename", "province"),
    "district": ("districtname", "district"),
    "sector": ("sectorname", "sector"),
    "cell": ("cellname", "cell"),
    "village": ("village", "villagename"),
    "upi": ("upi",),
    "size": ("size",),
    "land_use": ("land_use_name_kinyarwanda", "land_use", "landuse"),
    "transaction_type": ("transaction_type_name", "transaction_type"),
    "sale_price": ("sale_price", "price"),
    "start_date": ("start_date", "startdate", "date"),
    "year": ("year",),
}


def _to_float(val: str) -> float | None:
    val = (val or "").strip().replace(",", "")
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def parse_upi_csv(content: bytes | str) -> tuple[list[dict], list[str]]:
    """Return ``(rows, errors)``. Each row is a canonical dict; a row without a
    UPI is skipped with an error noted."""
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["CSV is empty or has no header row"]

    # Map each canonical field to the actual header present (if any).
    lower = {h.lower().strip(): h for h in reader.fieldnames}
    resolved: dict[str, str] = {}
    for field, aliases in _FIELD_ALIASES.items():
        for a in aliases:
            if a in lower:
                resolved[field] = lower[a]
                break

    if "upi" not in resolved:
        return [], ["CSV is missing a 'upi' column"]

    rows: list[dict] = []
    errors: list[str] = []
    for i, raw in enumerate(reader, start=2):  # row 1 is the header
        def g(field: str) -> str:
            col = resolved.get(field)
            return (raw.get(col) or "").strip() if col else ""

        upi = g("upi")
        if not upi:
            errors.append(f"row {i}: missing UPI — skipped")
            continue
        rows.append({
            "province": g("province") or None,
            "district": g("district") or None,
            "sector": g("sector") or None,
            "cell": g("cell") or None,
            "village": g("village") or None,
            "upi": upi,
            "size": _to_float(g("size")),
            "land_use": g("land_use") or None,
            "transaction_type": g("transaction_type") or None,
            "sale_price": _to_float(g("sale_price")),
            "start_date": g("start_date") or None,
            "year": g("year") or None,
        })
    return rows, errors
