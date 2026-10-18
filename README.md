# Parity Replay

**Parity Replay** tests the migration of wire-payment creation from the old Java 8 service (flat payment model, no
workflow) to the new Java 18 service (workflow model, ISO 20022 **pacs.008**, plus new features).

> Your old system already runs every day. This agent takes what it **already processed** — each request and the
> response it actually gave — feeds the same requests to the new code, and compares the answers. Bulk testing of
> 1,000 (or 100,000) real payments, with no change to the old system.

Its sibling product **Twin Run** ([`wirepay-dualrun-agent`](https://github.com/aidragons123/wirepay-dualrun-agent)), sends the same
request to both implementations live.

## Run it

```bash
pip install -r requirements.txt      # Streamlit, pandas, PyYAML, pytest
sudo apt-get install -y default-jdk  # only the bundled stand-in services need a JDK
make ui                              # Streamlit app
make replay                          # same thing from the command line -> out/report.{html,csv,json}
make replay-fixed                    # stand-in with its planted gaps fixed: 0 mismatches
make test
```

`make replay` also saves the run to the history (`--label NAME`, `--no-save`) and exits with code 1 when any payment mismatches, so it can gate a pipeline.

## What is in the app

| Page | What you do there |
|---|---|
| **New replay** | Configure and start a run. Every run is saved automatically. |
| **Overview** | A GO / NO-GO release banner, KPI tiles with change against your baseline, charts of where it differs, mismatch patterns with a suggested fix, trace and downloads. |
| **Payments** | Filter by verdict, rule, currency or id; select a payment to see old and new side by side, the rule-by-rule result, the new workflow path and the pacs.008 XML. |
| **Run history** | Every past run with a parity-over-time chart. Open, pin, rename, annotate, delete, set a baseline, or select two to compare. |
| **Compare runs** | Two runs on the same inputs: payments fixed, regressed, still failing; patterns resolved or new; rules that changed. |
| **Rules** | Latest rule results, the full rule library, and a form to add your own rule without code. |
| **Settings** | Release-gate limits, services under test, history bundle export and restore. |

Saved runs live in `.wirepay/` next to the app. **On Streamlit Community Cloud this folder is wiped whenever the app restarts or
sleeps**, so use *Settings → Download history bundle* before that, and *Restore* afterwards. Run locally and history is kept for good.

## What it does

```
 recorded old traffic          new Java 18 code             compare, rule by rule           diagnose
 {request, response} x 1000 -> request -> JSON + pacs.008 -> 14 mapping rules          ->  patterns, not rows
 (JSONL or CSV)                                              + 6 new-feature checks         + suggested fix
```

Every payment gets one verdict:

| Verdict | Meaning |
|---|---|
| ✅ **Match** | every applicable rule agrees |
| 🔷 **Expected difference** | differs, but only because of a documented new feature **and** an independent re-derivation confirms it (e.g. the IBAN really does fail mod-97) |
| ❌ **Mismatch** | a difference nothing documents, or a new feature that misbehaves — review it |

The report is rule-by-rule (like the COBOL RuleAgent): each mapping rule is **Validated**, **Invalidated** or **Not
exercised**, and mismatches are grouped into a handful of *patterns* with a suggested fix, because 46 failing payments
are usually 2 bugs.

### Sample result (bundled day of 1,000 payments)

| | |
|---|---|
| Exact match | 856 |
| Expected differences | 98 (34 bad IBAN checksums, 39 long names, 25 EUR bank holidays) |
| Mismatches | 46 → **2 patterns** |
| P-1 implementation defect | 29 same-day payments rejected by the new code (off-by-one in the past-date check) |
| P-2 rounding mode | 17 fees on an exact half cent: old rounds HALF_UP, new rounds HALF_EVEN |

## The new features it checks

| Id | New behaviour | How the agent treats it |
|---|---|---|
| N-001 | IBAN mod-97 checksum validation | old accepted, new rejected → expected **only if the checksum really fails** |
| N-002 | TARGET2 holiday-aware settlement date (EUR) | expected **only if** the date is a real closing day and the new date is the right next business day |
| N-003 | Full-length names (35 → 140 chars) | expected only if old is exactly the 35-char prefix of new |
| N-004 | UETR (UUIDv4) assigned | verified on every accepted payment |
| N-005 | Workflow audit trail | verified: starts at RECEIVED, only legal transitions, ends in the state matching the decision |
| N-006 | pacs.008 structurally complete | verified: all mandatory elements present |

The expected-difference checks use code that never touches the new service (`wirepay_core/explain.py`), so a
buggy new feature cannot excuse itself.

## Point it at your real code

The old system is **never called** — its answers come from the recording. Provide a capture file, and point the
agent at the new service.

**Capture format** (`data/…jsonl`, one object per line — or a CSV with `req_*` / `resp_*` columns):

```json
{"request":  {"requestId":"REQ1","debtorName":"…","debtorAccount":"DE89…","creditorName":"…","creditorAccount":"FR14…",
              "creditorBic":"DEUTDEFF","amount":"1000.00","currency":"USD","valueDate":"2026-10-22",
              "chargeBearer":"SHA","remittanceInfo":"Inv 1","processingDate":"2026-10-19"},
 "response": {"paymentId":"WP-REQ1","status":"ACCEPTED","errorCode":"","amount":"1000.00","currency":"USD",
              "fee":"15.00","settlementDate":"2026-10-22","debtorName":"…","creditorName":"…",
              "debtorAccount":"…","creditorAccount":"…","creditorBic":"DEUTDEFF","chargeBearer":"SHA","remittanceInfo":"Inv 1"}}
```

`processingDate` is the date the old system actually ran the payment; it is replayed to the new code so
"value date in the past" is judged against the same day.

**New service** — edit `agent.yaml`:

```yaml
new:
  type: http                      # POST each request as JSON; response JSON below
  url: https://wire-new.internal.example/api/payments
  headers: {Authorization: "Bearer <token>"}
```

The new service must return JSON with `paymentId`, `status` (`ACCP`/`RJCT`), `reasonCode`, `uetr`,
`workflow{finalState, history[{seq,state}]}` and `pacs008` (the XML string). If your real service shapes its
response differently, `wirepay_core/canonical.py → canon_new()` is the **one** place to adapt. A JVM main class that
reads one JSON request per line on stdin and writes one JSON response per line (`type: subprocess`) works too.

Add or change a rule without touching code: `wirepay_core/spec/mapping_rules.yaml`.

## About the bundled stand-ins — read this

Your real old and new code were not available when this was built, so `java/old` (Java 8 target) and `java/new`
(Java 18 target) are **stand-in implementations of the same use case**, there so the agent runs end to end. They
are not your code. The new stand-in contains **two deliberate parity gaps** (`PARITY-GAP-1/2` in
`WirePaymentProcessor.java`) so there is something real to find; `-Dwirepay.parityFix=true` (or "parity gaps
fixed" in the UI) removes them.

Things this does **not** do:
- It does not run the stand-ins on a real JDK 8 — they are *compiled* for Java 8 and run on whatever JVM is installed.
  Behavioural differences between JVM versions only appear when you point the agent at your real deployed services.
- pacs.008 checking is structural (mandatory elements, parseable). Full XSD validation needs the official schema
  files; they can be plugged in at `canon_new()`.
- Diagnosis is deterministic and rule-based. No LLM is called; an AI explainer could sit on top of the patterns later.

## Deploy on Streamlit Community Cloud

Main file `streamlit_app.py`; `packages.txt` installs a JDK. If the hosted JDK is older than 18, the new side is
compiled for the highest level available and the app says so.

## Layout

```
streamlit_app.py     UI              run_replay.py   CLI            agent.yaml   configuration
wirepay_core/        engine, store (history), diffing, gate, charts, shell + ui (the app)
  spec/mapping_rules.yaml           the rules
java/old, java/new   stand-in services (Java 8 / Java 18)
data/                recorded sample day (1,000 payments)           tests/       28 tests
```
