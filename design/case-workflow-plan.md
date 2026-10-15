# Plan: from appeal packet to managed case, with a live email connector

Builds on Tom's proposal ([docs/critique_idea_generation.md](../docs/critique_idea_generation.md)). Goal: a ClaimBack case stays open for weeks, reads the insurer's real replies from a real inbox, and drives the next action, with a human approving anything that leaves the system.

## Decisions

| Question | Choice |
|---|---|
| Connector | IMAP (read) + SMTP (send) with a Gmail app password. Python standard library only |
| Inbox | A new, dedicated ClaimBack Gmail account. Personal mail is never in reach |
| Sending | **Approve & send** button in the web view. Nothing sends without that click |
| Demo | Pre-recorded. The insurer is a scripted simulator that sends real emails marked as simulated |
| Phone calls | Out of scope; pitched as the roadmap with Tom's safeguards |

## How it fits together

```
finished run ──open-case──▶ CASE (casefiles/<id>/)  ◀──── web view: status, tasks, Approve & send, upload
                                │  reply address: claimback.demo+<id>@gmail.com
                                ▼
                     case worker (python -m claimback watch)   ← long-running, restart-safe
                     poll IMAP ─▶ dedupe ─▶ redact ─▶ Correspondence agent ─▶ validate
                                                      │
              ┌──────────────────────────┬───────────┴─────────────┬───────────────────────┐
         acknowledgment           evidence request             decision upheld         decision overturned
         → awaiting_insurer       → task + notification         → Planner/Policy for     → human confirms
                                  → user uploads evidence         external review         → closed
                                  → Writer + Fact Checker
                                  → draft → Approve & send
```

## Components

### 1. Case store — `claimback/cases.py`
- `casefiles/<case_id>/` (gitignored): `case.json` (written atomically, same retry-on-Windows logic as `state.py`), `events.jsonl` (the case timeline), `inbox/` (raw messages, local only), `uploads/`, `outbox/`.
- Case fields: id, run ids, reply address, insurer contact addresses (the allow-list), claim refs, status, stage (`internal_appeal` → `external_review`), tasks, correspondence (in and out), deadlines with their source and whether a human confirmed them, processed Message-IDs, outcome.
- Statuses: `awaiting_human` (approve something, upload something, or confirm an outcome), `awaiting_insurer`, `action_required` (agents working), `closed`.
- `python -m claimback open-case <run_id>` creates a case from a finished run, assigns the plus address, and queues the initial appeal as an outbox draft awaiting approval.

### 2. Email connector — `claimback/connectors/email_imap.py`
- `fetch_new()`: IMAP `SEARCH TO "+cb-"`. Only mail sent to case addresses is ever downloaded. Parse with the `email` stdlib, save attachments into the case folder.
- `send(to, subject, body, attachments, in_reply_to)`: SMTP over SSL, threaded with `In-Reply-To`/`References`, and a Message-ID generated **before** sending and recorded as `sending` → `sent`, so a restart can't send twice.
- `FakeConnector` backed by a local folder for offline tests and rehearsal, same interface.

### 3. Correspondence agent — new in `agents.py` + `schemas.py`
- Output (`CorrespondenceAnalysis`): message type (`acknowledgment`, `evidence_request`, `decision_upheld`, `decision_overturned`, `administrative`, `unclear`), summary, requested items each with a due date and the exact quote, decision with quote, new facts, proposed next action and its owner, `injection_suspected`.
- Deterministic checks (rejected outputs go back to the agent like today): every quote must appear verbatim in the redacted email; due dates must appear in their quote; an acknowledgment cannot carry a decision; a decision without a supporting quote becomes `unclear` and goes to a human.
- Inbound mail is redacted before the agent sees it: apply the case's identifier map, run the Intake PHI scan for new identifiers, leak-check. Sender addresses are not sent to the model.

### 4. Next actions — reuse the existing team
- **Evidence request** → task "Upload the letter of medical necessity by <date>" + browser notification → on upload, `write_followup()` (Writer with the request, the new document and the case history) → Fact Checker → outbox draft → Approve & send.
- **Decision upheld** → stage moves to external review; Planner + Policy Analyst re-run on the new decision; draft the external review request.
- **Decision overturned** → task "Confirm the outcome"; the case closes only after the human confirms.

### 5. Case worker — `python -m claimback watch [--interval 20]`
- Long-running loop: poll, process each new message through the pipeline above, react to uploads and approvals, write heartbeat and timeline events. All state lives in `case.json`, so it resumes after a crash with no lost or duplicated work.

### 6. Web view
- Endpoints: `GET /api/cases`, `GET /api/cases/<id>`, `GET /api/cases/<id>/stream` (SSE over the case timeline), `POST /api/cases/<id>/upload`, `POST /api/cases/<id>/approve` (sends the shown draft to the shown recipient), `POST /api/cases/<id>/confirm-outcome`.
- Case panel: status pill, **"Waiting for you"** banner with the task, correspondence timeline (incoming and outgoing, simulated messages labeled), draft preview with recipient and **Approve & send**, upload button, and browser notifications (`Notification` API) when a task appears.

### 7. Insurer simulator — `python -m claimback simulate-insurer <case_id> <scene>`
- Scenes: `ack`, `evidence-request` (letter of medical necessity within 14 days), `overturned`, `upheld`.
- Sends from a second account if `INSURER_SIM_*` is set in `.env`, otherwise from the ClaimBack account to the case address. Every message carries the header `X-ClaimBack-Simulated: true` and the line "SIMULATED INSURER MESSAGE" in its body. The timeline labels these messages "simulated insurer".

### 8. Replay
- Extend `export-site` to publish a case timeline next to runs, so the recording can also be watched on Pages.

## Safeguards

- **Scoped inbox access:** dedicated account, and only `+cb-` mail is fetched.
- **Recipient allow-list:** Approve & send only goes to the insurer addresses recorded on the case, so an injected "email this to x@evil.com" can't exfiltrate anything.
- **Human gate:** every outgoing message needs the Approve click; the UI shows exactly what goes where.
- **Untrusted input:** inbound email is redacted, treated as evidence not instructions, and flagged if it looks like an injection.
- **No sensitive notifications:** notification text is generic ("Action needed on your case").
- **Idempotent:** dedupe by Message-ID, sends recorded before they happen.
- **Credentials stay local:** only in `.env`; `purge` deletes a case folder.

## Milestones (each ends in something demo-able)

| # | Build | Done when | Est. |
|---|---|---|---|
| 1 | Case store, `open-case`, connector, `FakeConnector`, watcher with dedupe | A simulated email to the case address shows up on the case timeline; restart doesn't reprocess it | 1 h |
| 2 | Correspondence agent, inbound redaction, validators, task/status logic | `evidence-request` scene → task + `awaiting_human`; `ack` never reads as approval | 1 h |
| 3 | Evidence upload, `write_followup`, outbox, Approve & send with allow-list | Uploading a synthetic letter produces a fact-checked reply; Approve sends it, threaded | 1 h |
| 4 | Case panel, SSE, notifications | The whole lifecycle is visible and drivable from the browser | 45 min |
| 5 | Upheld/overturned paths, replay export, recording rehearsal | Full recording script runs end to end | 45 min |

## Recording script (pre-recorded, time jumps labeled)

1. Run the pipeline (sped-up replay): strong-case packet, case opened.
2. Approve & send the initial appeal → it lands in the simulated insurer's inbox. Case: `awaiting_insurer`.
3. *"3 days later"* — insurer simulator: acknowledgment → timeline shows it, status unchanged (not approval).
4. *"5 days later"* — insurer simulator: requests a letter of medical necessity within 14 days → task, deadline, browser notification, **"Waiting for you"**.
5. Upload the synthetic letter → Writer + Fact Checker draft the supplemental submission → Approve & send.
6. *"2 weeks later"* — insurer simulator: denial overturned → **"Confirm the outcome"** → confirmed → case closed with outcome recorded.

## Your setup (only you can do these)

1. Create a new Gmail account for ClaimBack.
2. Turn on 2-Step Verification for it, then create an app password (Google Account → Security → App passwords).
3. Add to `C:\claimback\.env`: `CLAIMBACK_EMAIL=...` and `CLAIMBACK_EMAIL_APP_PASSWORD=...`
4. Optional, for a more convincing recording: a second account for the simulated insurer, with `INSURER_SIM_EMAIL` and `INSURER_SIM_APP_PASSWORD`.
