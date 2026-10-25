"""Synthetic wire-payment requests, with realistic edge cases deliberately mixed in.

The share of each category is fixed by `WEIGHTS`, so a bulk run always contains cases that
exercise every rule. The category is returned separately and is never put in the request,
so the agents cannot "see" what was planted.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from .explain import target2_holiday

# category -> relative weight
WEIGHTS: dict[str, float] = {
    "clean": 56, "weekend": 5, "charge_our": 4, "charge_ben": 3, "special_chars": 3,
    "long_name": 4, "fee_tie": 4, "eur_holiday": 3, "same_day": 4, "iban_checksum": 3,
    "missing_field": 2, "bad_amount": 1.2, "over_limit": 1, "bad_currency": 1, "bad_bic": 1,
    "past_date": 1.2, "bad_account_shape": 1.2,
    "fraud_hold": 2.0, "fraud_resume": 1.5, "no_funds": 1.0, "duplicate": 1.2,
}

DEBTORS = ["Northwind Traders", "Acme Trading Ltd", "Blue Harbor Logistics", "Quantum Retail Inc",
           "Evergreen Foods Co", "Atlas Manufacturing", "Silverline Partners", "Orion Medical Supplies"]
CREDITORS = ["Müller GmbH", "Dupont & Fils SARL", "Van Dijk Handel BV", "Rossi Forniture SpA", "Zoë's Bakery Ltd",
             "Helvetia Maschinen AG", "Nakamura Trading KK", "Globex <Intl> Corp", 'O\'Brien "Fresh" Produce']
LONG_NAMES = ["International Consolidated Industrial Holdings Corporation",
              "Anglo-Continental Trading and Shipping Company Limited",
              "Pan-European Renewable Energy Infrastructure Partners"]
BICS = ["DEUTDEFF", "BNPAFRPP", "ABNANL2A", "UBSWCHZH80A", "NWBKGB2L", "CHASUS33XXX", "COBADEFFXXX", "INGBNL2A"]
REMITTANCE = ["Invoice 20418", "Order 77-1203 settlement", "Consulting services Q3", "Supply contract 55/B", ""]
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "INR", "CHF"]


def upcoming_holidays(proc: date, n: int = 6) -> list[date]:
    """The next n TARGET2 closing days after `proc` (so test data stays in the future)."""
    out, d = [], proc + timedelta(days=1)
    while len(out) < n:
        if target2_holiday(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def make_iban(country: str, rng: random.Random) -> str:
    """A valid IBAN (correct mod-97 check digits) for a handful of countries."""
    if country == "DE":
        bban = "".join(rng.choice("0123456789") for _ in range(18))
    elif country == "FR":
        bban = "".join(rng.choice("0123456789") for _ in range(23))
    elif country == "GB":
        bban = "NWBK" + "".join(rng.choice("0123456789") for _ in range(14))
    elif country == "NL":
        bban = "ABNA" + "".join(rng.choice("0123456789") for _ in range(10))
    else:  # CH
        bban = "".join(rng.choice("0123456789") for _ in range(17))
    digits = "".join(str(int(c, 36)) for c in bban + country + "00")
    check = 98 - int(digits) % 97
    return f"{country}{check:02d}{bban}"


def _corrupt(iban: str, rng: random.Random) -> str:
    i = rng.randrange(4, len(iban))
    ch = iban[i]
    repl = str((int(ch) + rng.randint(1, 8)) % 10) if ch.isdigit() else ("A" if ch != "A" else "B")
    return iban[:i] + repl + iban[i + 1:]


def _amount(rng: random.Random, currency: str) -> str:
    v = round(rng.lognormvariate(8.2, 1.3), 2)
    v = min(max(v, 50.0), 400000.0)
    return f"{round(v):d}.00" if currency == "JPY" else f"{v:.2f}"


def _base(i: int, rng: random.Random, proc: date) -> dict[str, Any]:
    ccy = rng.choices(CURRENCIES, weights=[40, 25, 12, 6, 10, 7])[0]
    cc = rng.choice(["DE", "FR", "GB", "NL", "CH"])
    domestic = rng.random() < 0.18
    vd = proc + timedelta(days=rng.randint(1, 20))
    return {
        "requestId": f"REQ{i:06d}",
        "debtorName": rng.choice(DEBTORS),
        "debtorAccount": "".join(rng.choice("0123456789") for _ in range(rng.randint(8, 12))) if domestic else make_iban("DE", rng),
        "creditorName": rng.choice(CREDITORS),
        "creditorAccount": make_iban(cc, rng),
        "creditorBic": rng.choice(BICS),
        "amount": _amount(rng, ccy),
        "currency": ccy,
        "valueDate": vd.isoformat(),
        "chargeBearer": "SHA",
        "remittanceInfo": rng.choice(REMITTANCE),
        "processingDate": proc.isoformat(),
    }


def _apply(cat: str, r: dict[str, Any], rng: random.Random, proc: date) -> None:
    if cat == "weekend":
        d = proc + timedelta(days=rng.randint(1, 20))
        while d.weekday() < 5:
            d += timedelta(days=1)
        r["valueDate"] = d.isoformat()
    elif cat == "charge_our":
        r["chargeBearer"] = "OUR"
    elif cat == "charge_ben":
        r["chargeBearer"] = "BEN"
    elif cat == "special_chars":
        r["creditorName"] = rng.choice(["Smith & Sons <Imports>", 'The "Golden" Fleece & Co', "Zoë O'Neill-Müller"])
        r["remittanceInfo"] = "Ref <A&B> \"quoted\""
    elif cat == "long_name":
        r["debtorName"] = rng.choice(LONG_NAMES)
        if rng.random() < 0.5:
            r["creditorName"] = rng.choice(LONG_NAMES)
    elif cat == "fee_tie":
        k = rng.randint(1500, 7499)                   # amount = k*10 + 5 dollars -> fee is an exact half cent
        r["amount"] = f"{k * 10 + 5}.00"
        r["currency"] = rng.choice(["USD", "EUR", "GBP"])
    elif cat == "eur_holiday":
        r["currency"] = "EUR"
        r["valueDate"] = rng.choice(upcoming_holidays(proc)).isoformat()
    elif cat == "same_day":
        r["valueDate"] = proc.isoformat()
    elif cat == "iban_checksum":
        key = rng.choice(["creditorAccount", "debtorAccount"])
        if not r[key][:2].isalpha():
            key = "creditorAccount"
        r[key] = _corrupt(r[key], rng)
    elif cat == "missing_field":
        r[rng.choice(["debtorName", "creditorAccount", "creditorBic", "amount", "currency", "valueDate"])] = ""
    elif cat == "bad_amount":
        r["amount"] = rng.choice(["abc", "-50.00", "0", "12,50"])
    elif cat == "over_limit":
        r["amount"] = f"{rng.randint(1000001, 5000000)}.00"
    elif cat == "bad_currency":
        r["currency"] = rng.choice(["XYZ", "CAD", "usd"])
    elif cat == "bad_bic":
        r["creditorBic"] = rng.choice(["DEUT12", "deutdeff", "BANK-1234"])
    elif cat == "past_date":
        r["valueDate"] = (proc - timedelta(days=rng.randint(1, 10))).isoformat()
    elif cat in ("fraud_hold", "fraud_resume"):
        if rng.random() < 0.5:
            r["creditorName"] = rng.choice(["Offshore Holdings Ltd", "Cayman Offshore Trading", "Blue Offshore Ventures"])
        else:
            r["currency"], r["amount"] = "USD", f"{rng.randint(750000, 990000)}.00"
        if cat == "fraud_resume":
            r["resumeFrom"] = "FRAUD_CHECK"
            r["fraudDecision"] = rng.choices(["RELEASE", "BLOCK"], weights=[3, 1])[0]
    elif cat == "no_funds":
        r["debtorAccount"] = f"{rng.randint(1000, 9999)}{rng.randint(100, 999)}0000"
    elif cat == "bad_account_shape":
        r[rng.choice(["debtorAccount", "creditorAccount"])] = rng.choice(["12AB", "X", "ABCDEFGH", "1234"])


def generate_requests(n: int, seed: int = 7, processing_date: date | str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (requests, categories). Deterministic for a given (n, seed, processing_date)."""
    proc = date.fromisoformat(processing_date) if isinstance(processing_date, str) else (processing_date or date.today())
    rng = random.Random(seed)
    cats = rng.choices(list(WEIGHTS), weights=list(WEIGHTS.values()), k=n)
    reqs = []
    for i, cat in enumerate(cats, start=1):
        r = _base(i, rng, proc)
        _apply(cat, r, rng, proc)
        reqs.append(r)
    # Some categories only make sense next to an earlier payment: a duplicate re-sends it, and a resume
    # continues the payment that was held at the fraud step (same requestId, sent later).
    for i, cat in enumerate(cats):
        if cat == "duplicate":
            earlier = [j for j in range(i) if cats[j] == "clean"]
            if earlier:
                reqs[i] = dict(reqs[rng.choice(earlier)])
            else:
                cats[i] = "clean"
        elif cat == "fraud_resume":
            held = [j for j in range(i) if cats[j] == "fraud_hold"]
            if held:
                reqs[i] = {**reqs[rng.choice(held)], "resumeFrom": "FRAUD_CHECK", "fraudDecision": reqs[i]["fraudDecision"]}
    return reqs, cats


SCENARIOS: dict[str, tuple[str, str]] = {
    # key -> (label, category)  used by the dual-run UI for one-click single requests
    "Clean USD payment": ("clean", "clean"),
    "Long party name (> 35 chars)": ("long_name", "long_name"),
    "Bad IBAN checksum": ("iban_checksum", "iban_checksum"),
    "EUR on a TARGET2 holiday": ("eur_holiday", "eur_holiday"),
    "Fee lands on an exact half cent": ("fee_tie", "fee_tie"),
    "Same-day value date": ("same_day", "same_day"),
    "Charge bearer OUR": ("charge_our", "charge_our"),
    "Special characters in names": ("special_chars", "special_chars"),
    "Over the payment limit": ("over_limit", "over_limit"),
    "Missing mandatory field": ("missing_field", "missing_field"),
    "Fraud flag: new code holds, old rejects": ("fraud_hold", "fraud_hold"),
    "Resume a held payment (release)": ("fraud_resume", "fraud_resume"),
    "Insufficient funds at posting": ("no_funds", "no_funds"),
}


def scenario_request(label: str, processing_date: date | str | None = None, seed: int = 11) -> dict[str, Any]:
    proc = date.fromisoformat(processing_date) if isinstance(processing_date, str) else (processing_date or date.today())
    rng = random.Random(seed + sum(map(ord, label)))
    r = _base(1, rng, proc)
    # scenario requests have a fixed, readable id
    r["requestId"] = "DEMO-" + "".join(w[0] for w in label.split() if w[0].isalnum()).upper()
    cat = SCENARIOS[label][1]
    _apply(cat, r, rng, proc)
    if cat == "clean":
        r["currency"], r["amount"] = "USD", "12500.00"
    elif cat == "fee_tie":
        # an even number of tenths of a cent-step: HALF_UP and HALF_EVEN genuinely disagree
        k = (int(float(r["amount"])) - 5) // 10
        r["amount"] = f"{(k + k % 2) * 10 + 5}.00"
    elif cat == "eur_holiday":
        # a weekday closing day, so the old (weekend-only) and new (holiday-aware) dates differ
        r["valueDate"] = next(d for d in upcoming_holidays(proc, 12) if d.weekday() < 5).isoformat()
    elif cat == "same_day":
        r["currency"], r["amount"] = "USD", "12500.00"
    return r
