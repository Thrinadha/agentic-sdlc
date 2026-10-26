# URL Shortener

Create short links, redirect them, and see click analytics. FastAPI + SQLAlchemy; SQLite locally,
PostgreSQL in production. The API contract is [`api/openapi.yaml`](api/openapi.yaml).

## Run
```bash
pip install -e .[dev]
uvicorn app.main:create_app --factory --port 8000
```

## Use
```bash
curl -s -X POST localhost:8000/api/v1/links -H 'content-type: application/json' \
     -d '{"url": "https://example.com/a/long/path", "custom_alias": "demo"}'
curl -i localhost:8000/demo                  # 307 -> https://example.com/a/long/path
curl -s localhost:8000/api/v1/links/demo/stats
curl -X DELETE localhost:8000/api/v1/links/demo
```

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/links` | create (201), alias taken (409), invalid (422) |
| `GET /api/v1/links/{code}` | metadata incl. click count |
| `DELETE /api/v1/links/{code}` | deactivate (204) |
| `GET /api/v1/links/{code}/stats` | total, last click, daily counts, top 5 referrers |
| `GET /{code}` | 307 redirect; 404 unknown; 410 expired |
| `GET /healthz` | liveness |

## Configuration
| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./shortener.db` | SQLAlchemy URL (`postgresql+psycopg://...` in production) |
| `BASE_URL` | `http://localhost:8000` | public origin used to build `short_url` |
| `SHORT_CODE_LENGTH` | `7` | generated code length |
| `CACHE_SIZE` / `CACHE_TTL_SECONDS` | `10000` / `300` | redirect cache |
| `STATS_DAYS` | `30` | window for daily stats |

## Test
```bash
pytest -q        # unit (tests/unit) + integration through the HTTP API (tests/integration)
```

## Design
- [ADR 0001: short code generation](docs/adr/0001-short-code-generation.md)
- [ADR 0002: redirects, caching and analytics](docs/adr/0002-redirects-caching-and-analytics.md)
- [Scalability and operations](docs/scalability.md)
