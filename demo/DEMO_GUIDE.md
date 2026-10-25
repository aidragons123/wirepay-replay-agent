# Demo guide: what is being compared, and where the AI helps

## What the agents compare
Two *running builds of the service*, never two source trees line by line.

1. **Source of each side** (Settings -> Services under test): the bundled stand-in, a **Git repository
   (any branch, tag or commit)**, or a deployed **HTTP endpoint**. Old and new are chosen independently, so they can
   be two branches of one repo, two commits, or two different repos.
2. **Build.** For Git, the agent clones into a private folder, checks out the ref, compiles it (or runs your build
   command) and records the commit SHA on the run.
3. **Test cases.** Generated payments (10 scenarios: valid, bad IBAN, weekend value date, same-day, long names, ...),
   or recorded or uploaded traffic.
4. **Run.** Live Agent sends the *same* payment (same processing date) to old and new. Replay Agent uses the answers
   already recorded from the old service and only calls the new one.
5. **Rules.** Every payment is checked against `wirepay_core/spec/mapping_rules.yaml` (M-001..M-014 field mappings and
   N-001..N-006 new features). Verdict per payment: match / explained difference / mismatch (plus technical error).
6. **Gate.** GO / NO-GO from the rules. The AI never decides it.

## The old and the new model in one picture
- **Old (no workflow):** one method runs the checks in a fixed order: basic validation, duplicate, fraud, bank details,
  posting. It stops at the first failure and stores nothing about how far a payment got. A fraud-flagged payment is rejected.
- **New (workflow):** the same steps are named, each with a status (done, failed, paused, restored), and kept as an audit
  trail. A fraud-flagged payment pauses at FRAUD_CHECK. Send it again with resumeFrom=FRAUD_CHECK and a decision
  (RELEASE or BLOCK) and it continues from that step; the earlier steps are not run again.
- **What the agent checks:** same decisions and fields wherever behaviour should be identical, and the workflow rules
  N-005 (legal ordered steps), N-007 (a held payment can be resumed), N-008 (resume skips completed steps).
- **Live example in the app:** Live Agent -> One payment -> "Fraud flag: new code holds, old rejects", then "Resume a held
  payment (release)". Open Payments in a batch run to see the step chips (green done, amber paused, dashed restored).

## Where the AI helps (say this out loud)
- Explains *why* a payment differs in plain English, using the payment, the rule and the new code.
- Groups mismatches into patterns and suggests the code fix for each pattern.
- Writes the release brief (what is safe, what blocks, what to fix first).
- Answers questions about the run ("which currencies fail?").
- Drafts new rules from a sentence.
Rules decide; the AI explains, suggests and drafts. That split is the point.

## 6-minute script
1. (30 s) Problem: migrating wire payments from Java 8 flat service to Java 18 ISO 20022 workflow service. Manual testing misses edge cases.
2. (60 s) Settings -> Services: Old = Git `legacy`, New = Git `modern`. Point out the commit SHAs. Create the repo with `python3 demo/make_demo_repo.py /tmp/wire-demo`.
3. (60 s) Live Agent -> Batch -> generate 1,000 -> send to both.
4. (60 s) Overview: success/failure/error %, NO-GO, 46 failures grouped in 2 patterns.
5. (90 s) AI analyst: release brief; open a mismatch -> "Explain with AI"; pattern -> "Suggest a fix".
6. (60 s) Switch New to branch `modern-fixed`, rerun: GO, 100% parity. Compare runs shows before/after.
