# ADR 0001: Short code generation

## Context
Codes must be short, unique, hard to guess and generated without a central bottleneck, so that
several instances can create links at the same time.

## Decision
Random 7-character base62 codes (`secrets.choice`), inserted under a unique constraint. On a
collision the insert fails and we retry with a new code (up to 5 attempts). Custom aliases use the
same column and get a 409 on conflict.

## Alternatives considered
| Option | Pros | Cons |
|---|---|---|
| Counter + base62 encoding | No collisions, shortest codes | Codes are sequential and guessable (enumeration); needs a central counter or ID ranges per instance |
| Hash of the URL (truncated) | Same URL gives the same code | Collisions on truncation still need handling; leaks that two users shortened the same URL |
| **Random base62 + unique constraint** | Unguessable, stateless, scales horizontally | Collision retries (negligible: at 100M links the chance per insert is ~3e-5) |

## Consequences
- 62^7 ≈ 3.5 × 10^12 codes. `SHORT_CODE_LENGTH` can grow without a migration.
- The database unique index is the single source of truth for uniqueness.
