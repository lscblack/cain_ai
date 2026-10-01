"""Phone number analysis via libphonenumber (offline, no network).

Produces an E.164 form, validity signals, geo/carrier metadata, and the common
textual variants a number may appear as on public pages. This is observed
metadata about the *number*, never a claim about who owns it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import phonenumbers
from phonenumbers import carrier, geocoder
from phonenumbers.phonenumberutil import NumberParseException, PhoneNumberType

_TYPE_NAMES = {
    PhoneNumberType.FIXED_LINE: "fixed_line",
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_line_or_mobile",
    PhoneNumberType.TOLL_FREE: "toll_free",
    PhoneNumberType.PREMIUM_RATE: "premium_rate",
    PhoneNumberType.SHARED_COST: "shared_cost",
    PhoneNumberType.VOIP: "voip",
    PhoneNumberType.PERSONAL_NUMBER: "personal_number",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "uan",
    PhoneNumberType.VOICEMAIL: "voicemail",
    PhoneNumberType.UNKNOWN: "unknown",
}


@dataclass
class PhoneAnalysis:
    input: str
    parsed: bool
    valid: bool = False
    possible: bool = False
    e164: str | None = None
    international: str | None = None
    national: str | None = None
    country_code: int | None = None
    region: str | None = None
    location: str | None = None
    carrier: str | None = None
    number_type: str = "unknown"
    variants: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "input": self.input,
            "parsed": self.parsed,
            "valid": self.valid,
            "possible": self.possible,
            "e164": self.e164,
            "international": self.international,
            "national": self.national,
            "country_code": self.country_code,
            "region": self.region,
            "location": self.location,
            "carrier": self.carrier,
            "number_type": self.number_type,
            "variants": self.variants,
            "error": self.error,
        }


def _variants(num: phonenumbers.PhoneNumber) -> list[str]:
    e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    intl = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    natl = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)
    digits = re.sub(r"\D", "", e164)  # country+national digits, no plus
    national_digits = str(num.national_number)
    out = {
        e164,                       # +250788123456
        digits,                     # 250788123456
        national_digits,            # 788123456
        f"0{national_digits}",      # 0788123456 (common national prefix)
        intl,
        natl,
    }
    return sorted(out)


def analyze_phone(raw: str, default_region: str | None = None) -> PhoneAnalysis:
    raw = (raw or "").strip()
    result = PhoneAnalysis(input=raw, parsed=False)
    if not raw:
        result.error = "empty"
        return result
    try:
        num = phonenumbers.parse(raw, default_region)
    except NumberParseException as exc:
        result.error = str(exc)
        return result

    result.parsed = True
    result.valid = phonenumbers.is_valid_number(num)
    result.possible = phonenumbers.is_possible_number(num)
    result.country_code = num.country_code
    result.region = phonenumbers.region_code_for_number(num)
    result.e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    result.international = phonenumbers.format_number(
        num, phonenumbers.PhoneNumberFormat.INTERNATIONAL
    )
    result.national = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)
    result.location = geocoder.description_for_number(num, "en") or None
    result.carrier = carrier.name_for_number(num, "en") or None
    result.number_type = _TYPE_NAMES.get(phonenumbers.number_type(num), "unknown")
    result.variants = _variants(num)
    return result
