---
id: REQ-202
title: Fix bookmark paging and add tag filter
scenario: bookmarks
seed: examples/seeds/bookmarks-api
seed_version: 1.2.0
---
Two things on the existing Bookmarks API:

1. **Bug:** users report that paging through `GET /bookmarks` loses bookmarks. With 45 bookmarks and the
   default page size, the pages don't add up to 45.
2. **Enhancement:** let clients filter the list by tag, e.g. `GET /bookmarks?tag=python`. Matching should
   ignore case. Paging and `total` should apply to the filtered list.

Add regression tests and keep the API docs up to date. Existing clients must keep working.
