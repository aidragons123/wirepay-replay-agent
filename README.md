# Replay Agent

**Replay Agent** tests the migration of wire-payment creation from the old Java 8 service (flat payment model, no
workflow) to the new Java 18 service (workflow model, ISO 20022 **pacs.008**, plus new features).

> Your old system already runs every day. This agent takes what it **already processed** — each request and the
> response it actually gave — feeds the same requests to the new code, and compares the answers. Bulk testing of
> 1,000 (or 100,000) real payments, with no change to the old system.

Its sibling product **Live Agent** ([`wirepay-dualrun-agent`](https://github.com/aidragons123/wirepay-dualrun-agent)), sends the same
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

## The AI analyst

Claude is used for what rules cannot do: reading results and explaining them. **The rule engine still decides every verdict and the
GO / NO-GO gate; the AI cannot change them.** It is off until you add an Anthropic API key (Settings, AI assistant, or the
`ANTHROPIC_API_KEY` secret on Streamlit Cloud). Without a key the rest of the app works unchanged.

| Where | What Claude does |
|---|---|
| Overview, Mismatch patterns | **Suggest a fix with AI**: reads the mismatch pattern, its examples and the new-service code (comments stripped, so it finds the cause from the logic) and proposes the root cause and a before/after change. You can paste your own code. |
| Payments | **Explain with AI**: why this payment differs and whether that is expected. |
| AI analyst, Release brief | A short brief for a delivery manager: decision, expected changes, problems, next step. |
| AI analyst, Ask about this run | Chat grounded in the run's facts ("Which rule fails most?", "What should I fix first?"). |
| Rules, Add your own rule | Describe a rule in plain English; Claude drafts it and the engine validates it before you add it. |

Privacy: IBANs are masked before sending by default (first four and last two characters kept). Names and amounts are still sent, so use
test data or data you are allowed to share. If your key is organisation-wide and not tied to a workspace, also enter the workspace ID (Settings, or the `ANTHROPIC_WORKSPACE_ID` secret). The default model is `claude-sonnet-5-5`; change it in Settings or with `WIREPAY_AI_MODEL`.

## What it does

```
 recorded old traffic          new Java 18 code             compare, rule by rule           diagnose
 {request, response} x 1000 -> request -> JSON + pacs.008 -> 14 mapping rules          ->  patterns, not rows
 (JSONL or CSV)                                              + 8 new-feature checks         + suggested fix
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

## Compare two Git branches, tags or commits

Settings -> Services under test -> **Git repository**. Here only the new side is built, so you can replay the same recorded traffic against any branch or commit. The agent clones into its own folder, checks out the ref,
compiles it with `javac` (or runs your build command, e.g. `mvn -q package`, and uses the classpath you give) and runs
it. Every run stores the commit it tested (`name@ref . sha`). It only reads; it never pushes. For private repositories
paste an access token (kept for the browser session only).

The entry class must speak the batch protocol of the stand-ins (one JSON request per line on stdin, one JSON answer
per line on stdout). A service that cannot do that should be deployed and used through the HTTP option instead.

Try it locally: `python3 demo/make_demo_repo.py /tmp/wire-demo` builds a repo with branches `legacy`, `modern` and
`modern-fixed`; use that path as the repository. On Streamlit Community Cloud a local path does not exist, so push that
repo to GitHub and use its https URL. See `demo/DEMO_GUIDE.md` for the demo script.

## How the old and new services process a payment

| Step | Old service (no workflow) | New service (workflow) |
|---|---|---|
| 1 Basic validation | mandatory fields, amount, currency, value date | same checks, recorded as step `BASIC_VALIDATION` |
| 2 Duplicate check | same request id seen before: reject `E008` | step `DUPLICATE_CHECK`: reject `DUPL` |
| 3 Fraud check | flagged payment is **rejected** `E009`; it cannot wait | flagged payment **pauses** at `FRAUD_CHECK` (status `PDNG`) |
| 4 Bank details | BIC and account number checks (`E004`, `E006`) | step `BANK_DETAILS_CHECK`, plus the IBAN checksum |
| 5 Posting | fee, settlement date, ledger post (`E010` no funds) | step `POSTING`, then `COMPLETED` with a pacs.008 message |

The old service runs the checks inline, top to bottom, and stores nothing about how far a payment got. The new one
records every step with a status (`DONE`, `FAILED`, `PAUSED`, `RESTORED`). A payment paused at the fraud step is
continued by sending it again with `resumeFrom=FRAUD_CHECK` and `fraudDecision=RELEASE` or `BLOCK`: the earlier steps
come back as `RESTORED` and are not run again. The old service can only treat the re-sent payment as a new one,
which it rejects as a duplicate. Fraud rule used by both: amount of 750,000 or more, or a creditor name containing "OFFSHORE".

## The new features it checks

| Id | New behaviour | How the agent treats it |
|---|---|---|
| N-001 | IBAN mod-97 checksum validation | old accepted, new rejected → expected **only if the checksum really fails** |
| N-002 | TARGET2 holiday-aware settlement date (EUR) | expected **only if** the date is a real closing day and the new date is the right next business day |
| N-003 | Full-length names (35 → 140 chars) | expected only if old is exactly the 35-char prefix of new |
| N-004 | UETR (UUIDv4) assigned | verified on every accepted payment |
| N-005 | Workflow audit trail | verified: steps in order, each with a status, ending in the state that matches the decision |
| N-006 | pacs.008 structurally complete | verified: all mandatory elements present |
| N-007 | Fraud hold pauses at the fraud step | old rejected (E009), new holds: expected **only if** the independent fraud screen flags it; also verified that a held payment is resumable |
| N-008 | Resume continues from the paused step | old cannot resume (E008/E009): expected **only if** earlier steps came back `RESTORED` and were not re-run |

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
- Verdicts and the gate are deterministic and rule-based. The AI analyst (optional) only explains and suggests; it never decides.

## Deploy on Streamlit Community Cloud

Main file `streamlit_app.py`; `packages.txt` installs a JDK. If the hosted JDK is older than 18, the new side is
compiled for the highest level available and the app says so.

## Layout

```
streamlit_app.py     UI              run_replay.py   CLI            agent.yaml   configuration
wirepay_core/        engine, store (history), diffing, gate, charts, shell + ui (the app)
  spec/mapping_rules.yaml           the rules
java/old, java/new   stand-in services (Java 8 / Java 18)
data/                recorded sample day (1,000 payments)           tests/       48 tests
```
