# Review: REQ-202 - Fix bookmark paging and add tag filter

**Verdict:** approve with comments

Minimal, well-scoped change: the fix is one line in BookmarkStore.list with regression tests that fail on the old code, and the filter reuses the same method instead of adding a parallel code path. Existing tests still pass, so clients without `tag` are unaffected.

## Story coverage
```
  ✔ AC1 done - store.list slice fix; test_pages_add_up_to_total, test_full_page_has_exactly_size_items
  ✔ AC2 done - casefold exact match; test_filter_by_tag_ignores_case, test_tag_is_an_exact_match_not_a_substring
  ✔ AC3 done - filter before slice; test_paging_applies_to_filtered_list
  ✔ AC4 done - existing tests/test_api.py unchanged and passing; test_without_tag_lists_everything, test_out_of_range_paging_is_rejected
  ✔ AC5 done - docs/api.md 'Filtering by tag' and changelog
```

## Findings (most important first)
| Severity | Check | Location | Problem | Suggested fix | Source |
|---|---|---|---|---|---|
| LOW | patterns | bookmarks/store.py:39 | Tags are compared with casefold() on every request; storing a normalised copy on write would avoid the repeated work. | Follow-up when a persistent store is introduced: keep a lower-cased tag column with an index. | agent |
| LOW | missed scenario | bookmarks/api.py:24 | Whitespace-only tags (`?tag=%20`) are accepted and simply match nothing. | Optional: strip and reject blank tags; harmless today. | agent |

## Missed scenarios
- Concurrent add during paging can shift items between pages (offset paging); cursor paging would fix it, out of scope.

## Fixes
No fixes proposed.
