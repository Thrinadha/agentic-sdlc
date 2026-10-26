# Notification Service

Receives order events and delivers per-user notifications to an in-app inbox, respecting each user's
preferences. Contract: [`api/openapi.yaml`](api/openapi.yaml). Design: [ADR 0001](docs/adr/0001-channels-and-delivery.md).

## Run and test
```bash
pip install fastapi uvicorn httpx pytest
uvicorn notify.main:create_app --factory --port 8001
pytest -q
```

## Use
```bash
# the order system publishes an event (safe to resend: duplicates are ignored)
curl -s -X POST localhost:8001/api/v1/events -H 'content-type: application/json' -d \
  '{"event_id":"e-1","type":"order_shipped","user_id":"alice","order_id":"o-1","occurred_at":"2026-10-01T10:00:00Z"}'

curl -s localhost:8001/api/v1/users/alice/notifications?unread=true
curl -s -X POST localhost:8001/api/v1/users/alice/notifications/1/read
curl -s -X PUT localhost:8001/api/v1/users/alice/preferences -H 'content-type: application/json' \
  -d '{"in_app": {"order_shipped": false}}'
```

Event types: `order_shipped`, `order_delivered`, `order_cancelled`. All are on by default.

## Limits of v1
In-memory state (single instance), in-app channel only, no authentication (internal service behind the
gateway). See the ADR for the path to email delivery and a persistent store.
