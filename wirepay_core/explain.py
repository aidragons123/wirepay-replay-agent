"""Independent re-derivations used to explain (or refute) differences.

Nothing here calls the new code. If the new service claims "this IBAN is bad" or
"this is a bank holiday", these functions decide whether that claim is true.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

IBAN_SHAPE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
UETR_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

FEE_RATE, FEE_MIN, FEE_MAX, OUR_SURCHARGE = Decimal("0.001"), Decimal("15.00"), Decimal("75.00"), Decimal("10.00")
CENT = Decimal("0.01")
NAME_LIMIT_OLD = 35

ALLOWED_TRANSITIONS = {
    "RECEIVED": {"VALIDATED", "REJECTED"},
    "VALIDATED": {"ENRICHED", "REJECTED"},
    "ENRICHED": {"ACCEPTED", "REJECTED"},
    "ACCEPTED": set(),
    "REJECTED": set(),
}


def is_iban_shaped(a: str) -> bool:
    return bool(IBAN_SHAPE.match(a))


def iban_checksum_ok(iban: str) -> bool:
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def iban_invalid(account: str) -> bool:
    """True if the account looks like an IBAN but fails mod-97."""
    return is_iban_shaped(account) and not iban_checksum_ok(account)


def any_iban_invalid(req: dict) -> bool:
    return iban_invalid(str(req.get("debtorAccount", "")).strip()) or iban_invalid(str(req.get("creditorAccount", "")).strip())


def easter_sunday(year: int) -> date:
    """Meeus/Jones/Butcher algorithm."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def target2_holiday(d: date) -> bool:
    if (d.month, d.day) in {(1, 1), (5, 1), (12, 25), (12, 26)}:
        return True
    e = easter_sunday(d.year)
    return d in (e - timedelta(days=2), e + timedelta(days=1))


def settlement_date(value_date: date, currency: str, holiday_aware: bool) -> date:
    d = value_date
    while d.weekday() >= 5 or (holiday_aware and currency == "EUR" and target2_holiday(d)):
        d += timedelta(days=1)
    return d


def fee_variants(amount: Decimal, bearer: str) -> dict[str, Decimal]:
    """The fee under each rounding mode, plus the exact unrounded value."""
    exact = amount * FEE_RATE
    out = {}
    for name, mode in (("HALF_UP", ROUND_HALF_UP), ("HALF_EVEN", ROUND_HALF_EVEN)):
        fee = min(max(exact.quantize(CENT, rounding=mode), FEE_MIN), FEE_MAX)
        if bearer == "OUR":
            fee += OUR_SURCHARGE
        out[name] = fee
    return out


def effective_bearer(raw: str) -> str:
    return raw if raw in ("OUR", "BEN") else "SHA"
