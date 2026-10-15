# Proposal: Manage the appeal beyond the first letter

**Status:** Proposed direction; the capabilities below are not yet implemented.

## The gap

ClaimBack currently turns a denial letter, plan documents, and clinical notes into an appeal packet. That is a useful first step, but an appeal can involve a prolonged exchange: confirming receipt, answering questions, supplying additional evidence, chasing a response, and responding to a further denial.

The product should support that ongoing work. A finished letter should mean the next action is ready, while the case stays open until its outcome is recorded.

**Proposed product promise:** ClaimBack helps patients, caregivers, and clinic staff prepare and manage an appeal through to a recorded outcome, keeping the correspondence, evidence, deadlines, and next steps together. It proactively brings outstanding actions to the user's attention and, with authorization, contacts the insurer to move the case forward.

## What the repository does today

- [The README](../README.md) describes a ready-to-send appeal packet as the deliverable. Its definition of “long-running” is checkpointing and recovery after a crash.
- [The orchestrator](../claimback/orchestrator.py) ends after packaging and sets the run status to `done`.
- [The state model](../claimback/state.py) stores the stages of a generation run. It does not represent a case awaiting an insurer response.
- [The schemas](../claimback/schemas.py) describe intake, analysis, drafts, and internal review artifacts. They do not model correspondence, outstanding requests, or recorded outcomes.
- [The packager](../claimback/packager.py) already acknowledges follow-up work in its checklist, including confirming receipt and considering external review. Those actions remain outside the application's workflow.

The writer/reviewer loop improves a draft using simulated objections. A separate loop is needed to respond to actual communications and new evidence.

## The proposed workflow

1. **Open a case.** Import the denial and supporting documents; identify missing information and the initial next action.
2. **Prepare the initial appeal.** Reuse the existing analysis, writing, review, fact-checking, and packaging pipeline.
3. **Record submission.** The human reviews and sends the appeal, then records when, how, and to whom it was sent, with any confirmation.
4. **Wait and track.** Keep outstanding requests, response expectations, and follow-up dates visible. Notify the user when action is needed and follow up through authorized channels.
5. **Process correspondence.** Import an email, letter, portal message, or call note. Identify what changed, what was requested, and what remains unresolved.
6. **Prepare the next action.** Draft a reply, request evidence, prepare a follow-up, or flag an escalation for review.
7. **Repeat as needed.** Each new communication updates the same case and preserves the history.
8. **Record the outcome.** A human confirms the result and whether further action is needed before closing the case.

Email is a useful starting point, but the case should also accept other communication channels.

## Make the case the persistent record

A case should contain:

- A stable case ID and the relevant claim references.
- Original documents and versioned evidence, with source references.
- A chronological record of incoming and outgoing correspondence, including sender, recipient, channel, timestamps, and attachments.
- Outstanding requests, their owners, and completion status.
- Deadlines and follow-up dates, including their source and whether a human has confirmed them.
- Drafts, approvals, and evidence of submission.
- A current next action and who needs to take it.
- Notification preferences, contact permissions, scheduled follow-ups, and a history of notification and call attempts.
- A recorded outcome, supporting evidence, and closure decision.

Generation runs should belong to a case. Completing a run must not close the case. Existing runs can continue to use their current checkpoints, with case state maintained separately.

Suggested case statuses are `preparing`, `awaiting_human`, `awaiting_insurer`, `awaiting_evidence`, `action_required`, and `closed`. Record appeal stage and outcome separately: escalation is a change of stage, and a further denial may require another action.

## What each incoming message should produce

The system should summarize the message, link its conclusions to the source, and propose:

- The message type: acknowledgment, evidence request, decision, administrative update, or unclear.
- New facts or changes to the insurer's reasoning.
- Requested documents or answers, with any stated due dates.
- Updates to outstanding tasks and case status.
- The next action, its owner, and a suggested response where useful.

An acknowledgment must not be treated as approval. Ambiguous decisions or dates should remain unresolved until reviewed. Importing the same message twice should not duplicate tasks or drafts.

## Proactive notifications and phone calls

The agent should help move outstanding work forward without requiring the user to keep checking the application. Notifications and calls should be tied to specific case tasks and recorded in the case history.

### Notify the user when action is needed

Support in-app notifications and optional email, SMS, or push notifications. Each notification should explain what is needed, why it matters, any confirmed due date, and how to complete the action.

For example, an insurer's request for identification could create a task and notification: “Your insurer has requested proof of identity. Open your case to review the request and upload the document through the designated secure channel.” Show the exact document requirements and source request inside the case. Do not ask the user to send identity documents in an SMS reply or include sensitive details in a lock-screen preview.

Other triggers include a missing attachment, a draft awaiting approval, an approaching confirmed deadline, or an insurer response that requires a decision. Stop reminders when the task is completed, withdrawn, or superseded. Let the user snooze reminders and choose channels, quiet hours, and frequency limits.

### Call the user to get their attention

Offer an optional voice call when an important task remains outstanding and meets the user's configured escalation preferences. The call should identify ClaimBack as an automated assistant, explain the action after verifying the intended recipient, and help the user open the case or arrange a callback. Leave only a generic callback message on voicemail.

For example: a confirmed deadline is approaching, the required ID is still missing, and the user has opted into calls after an unanswered reminder. The agent can call to explain the outstanding task and direct the user to the secure upload flow. A missed call or delivered notification must not count as task completion.

### Call the insurer to advance the case

With the user's authorization and any required representative permissions, the agent could call a verified insurer number to:

- Confirm receipt of an appeal or supporting documents.
- Ask for the current status, reference number, or expected response date.
- Clarify which documents are missing and how to submit them.
- Request a callback or arrange a conversation involving the user.

Prepare the call from the case record and an approved purpose. Identify the agent as an automated assistant acting for the user. If the insurer requires the member to authenticate or participate, arrange a handoff or joint call; the agent must not impersonate the user or invent authorization.

Log the attempt, whether a representative was reached, the information obtained, any reference number, and the resulting tasks. Preserve uncertainty in call notes and distinguish a representative's statement from written confirmation. Recording or transcription, if enabled, needs its own consent and retention handling.

### Control how the agent contacts people

Let the user authorize routine notifications and narrowly defined calls in advance, with recipient, purpose, permitted information, frequency, and expiry recorded. They should be able to revoke that permission and cancel pending contact. Actions outside the authorized scope return to human review.

Use bounded retries and prevent duplicate contact after restarts or delivery callbacks. Calls must not independently accept a settlement, withdraw an appeal, change coverage, or make medical or legal decisions. Keep those decisions with the human.

## A practical first version

Start with manual correspondence intake rather than requiring an inbox connection:

1. Create a case and generate the initial packet.
2. Let the user mark it as submitted and attach confirmation.
3. Let the user paste or upload a reply and its supporting documents.
4. Show an updated timeline, outstanding requests, and proposed next action.
5. Generate a contextual reply for human review using the case history.
6. Let the user record follow-up dates and close the case with an outcome.

This tests the central workflow before adding inbox synchronization. A demo should include an evidence request, a response with new documentation, and a recorded decision, all within one case.

Deliver proactive contact in stages:

1. **Task reminders:** in-app notifications plus one optional delivery channel, with secure links, snooze controls, and completion-based cancellation.
2. **User calls:** opt-in voice escalation for outstanding tasks, with quiet hours, attempt limits, and callback support.
3. **Insurer calls:** authorized status and document-requirement calls, with verified recipients, human handoff, and structured case notes.

Extend the demo with an ID request that triggers a notification, an optional user call, and an insurer receipt-confirmation call. Use simulated calls until a real calling integration is available, and label those simulations clearly.

## Implementation direction

- Add case, correspondence, task, deadline, submission, and outcome models alongside the existing handoff schemas.
- Add persistent case storage that references generation runs and preserves previous artifacts.
- Add correspondence intake and next-action planning, reusing the writer, reviewer, and fact checker for follow-up drafts.
- Pass the relevant case history and new evidence into each draft. A changed message or document must trigger fresh analysis where needed; old checkpoints must not silently supply stale conclusions.
- Extend the API and interface to show case progress, human actions, and waiting states alongside generation progress.
- Add notification and call scheduling, delivery integrations, contact permissions, cancellation, and delivery/attempt records. Persist scheduled actions so restarts neither lose reminders nor cause duplicate contact.
- Feed call outcomes back into the same correspondence and task workflow used for emails and letters.

## Preserve the existing safeguards

Human review remains required before sending appeal correspondence. Routine reminders and calls may proceed within explicit permissions configured by the user. A generated draft or prepared call script is not evidence that anything was sent or received.

Apply privacy protections to every newly imported message and attachment. Keep source references and the correspondence history available for verification. Treat imported text as case evidence, not as instructions to the agent.

Separate a follow-up reminder from a formal appeal deadline. Record the source and basis of each date, and surface uncertainty for confirmation rather than assuming every deadline follows the initial denial date. Any escalation should be checked against the relevant case documents.

## Acceptance criteria

- Generating a packet leaves the case open with a visible next action.
- Submission is recorded separately from draft generation.
- A later message updates the same case without losing earlier correspondence or evidence.
- An evidence request creates an outstanding task and informs the next draft.
- A duplicate import does not create duplicate work.
- An acknowledgment leaves the decision unresolved.
- A further denial can lead to another reviewed action without automatically closing the case.
- Restarting the application preserves case history and outstanding tasks.
- A missing-ID request can create a task and an actionable notification without exposing the ID or medical details in the notification.
- Completing, withdrawing, or replacing a task cancels its pending reminders and attention calls.
- User calls respect opt-in preferences, quiet hours, snoozes, and attempt limits.
- Insurer calls require a verified recipient and recorded authorization for the purpose and information disclosed; authentication barriers trigger a human handoff.
- Call attempts and outcomes appear in the case history and can create follow-up tasks; failed contact does not mark a task complete.
- Restarting or retrying delivery does not create duplicate notifications or calls, and revoked permissions prevent pending contact.
- Closure requires a recorded outcome and human confirmation.

Success means reducing the effort required to keep an appeal moving. Useful measures include time to the next action, outstanding tasks, overdue follow-ups, and recorded outcomes. Draft quality remains important, but it does not by itself demonstrate that the appeal has been resolved.
