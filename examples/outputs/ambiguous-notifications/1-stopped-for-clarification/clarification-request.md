# Clarification needed: REQ-303 User notifications

The run stopped before planning because these questions change the architecture or API.
Answer them in a YAML file (`<id>: <answer>`) and rerun with `--answers <file>`, or run
interactively.

## Q1: Which events should trigger a notification, and which system produces them?
- Why it matters: Defines the event schema, the ingestion API and the message templates.
- Default if you accept it: Order lifecycle events from the order system.

## Q2: Which delivery channels: in-app, email, SMS, push?
- Why it matters: Email/SMS/push need provider integrations, retries and queued delivery; in-app does not.
- Default if you accept it: In-app inbox only, designed so channels can be added.

## Q3: What does 'fast' mean: a latency target from event to the user seeing it?
- Why it matters: Seconds allows synchronous fan-out; sub-second at scale or slow channels needs a queue and workers.
- Default if you accept it: Visible within 5 seconds p95.
