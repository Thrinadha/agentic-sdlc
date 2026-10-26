# Engineering summary: REQ-303 User notifications

| Field | Value |
|---|---|
| Run | `20261025-225153-a73ad3` |
| Scenario | notifications |
| Provider | mock |
| Phase | needs_clarification |
| Branch | `REQ-303-user-notifications` |
| Commit | - |
| LLM calls | 1 |

## 1. Requirement (normalized)
**Kind:** greenfield
**Intent:** Users hear about events that matter to them quickly and can control what they receive.

The requirement does not say which events trigger notifications, through which channels they are delivered, or what 'fast' means. Each of these changes the data model, the public API and the architecture (synchronous vs queued delivery), so they must be answered before planning.

**Acceptance criteria**
- AC1: Users receive a notification for each relevant event (events to be defined).
- AC2: Users can choose which notifications they receive.
- AC3: Notifications are delivered within an agreed latency target (to be defined).

**Non-functional**
- Latency target: undefined ('fast')

**Out of scope**
- none

## 2. Ambiguities and how they were resolved
| Id | Severity | Question | Resolution |
|---|---|---|---|
| Q1 | blocking | Which events should trigger a notification, and which system produces them? | Order lifecycle events from the order system. |
| Q2 | blocking | Which delivery channels: in-app, email, SMS, push? | In-app inbox only, designed so channels can be added. |
| Q3 | blocking | What does 'fast' mean: a latency target from event to the user seeing it? | Visible within 5 seconds p95. |
| Q4 | minor | How fine-grained is control: global mute, per event type, per channel? | Per channel, per event type; everything on by default. |
| Q5 | minor | Can the producer send the same event twice? | Yes; ingestion is idempotent by event_id. |

## 3. Validation
_not run_

## 4. Human oversight (gate audit log)
| Gate | Decision | By | When | Note |
|---|---|---|---|---|
| clarify | rejected | policy:answers_or_stop | 2026-10-25 22:52:15 | needs a human answer for: Q1, Q2, Q3 |

Approvals here were given by the written gate policy (`--policy auto`, used for this unattended run). Interactively, a human answers each gate; blockers are never auto-approved.

## 5. Assumptions and limitations
- Generated code is validated by tests, lint, an unsafe-pattern scan, a contract check and a secret scan; it is not load tested here. Scalability claims are design-level.
- With the mock provider the agents' answers are pre-written fixtures, not live model output; the orchestration, gates, git operations and all validation run for real.
