# Bookmarks API

A small service to save and list bookmarks. API reference: [docs/api.md](docs/api.md).

```bash
pip install fastapi uvicorn httpx pytest
uvicorn bookmarks.main:create_app --factory
pytest -q
```
