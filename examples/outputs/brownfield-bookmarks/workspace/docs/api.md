# Bookmarks API

| Method | Path | Description |
|---|---|---|
| `POST` | `/bookmarks` | Create a bookmark: `{"url", "title", "tags": []}` → 201 |
| `GET` | `/bookmarks?page=1&size=20&tag=python` | List bookmarks, newest first. `page` ≥ 1, `size` 1–100, optional `tag` |
| `GET` | `/bookmarks/{id}` | One bookmark, or 404 |
| `DELETE` | `/bookmarks/{id}` | Delete, 204, or 404 |

List responses: `{"items": [...], "total": <matching bookmarks>, "page": 1, "size": 20}`.

## Filtering by tag
`tag` is optional. When given, only bookmarks that have that tag are returned. Matching ignores case
(`?tag=Python` matches a bookmark tagged `python`) and is exact, not a substring. Paging and `total`
apply to the filtered list. Without `tag` the response is unchanged from earlier versions.

## Changelog
- **1.3.0**: `tag` filter on `GET /bookmarks`; fixed paging so every page returns `size` items
  (previously each page returned one item fewer and that bookmark was never shown).
