# Bookmarks API

| Method | Path | Description |
|---|---|---|
| `POST` | `/bookmarks` | Create a bookmark: `{"url", "title", "tags": []}` → 201 |
| `GET` | `/bookmarks?page=1&size=20` | List bookmarks, newest first. `page` ≥ 1, `size` 1–100 |
| `GET` | `/bookmarks/{id}` | One bookmark, or 404 |
| `DELETE` | `/bookmarks/{id}` | Delete, 204, or 404 |

List responses: `{"items": [...], "total": <all bookmarks>, "page": 1, "size": 20}`.
