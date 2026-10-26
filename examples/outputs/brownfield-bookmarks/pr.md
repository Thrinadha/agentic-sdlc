# REQ-202 - Fix bookmark paging and add tag filter

## Description
Implements REQ-202

**Summary**
GET /bookmarks drops items when paging: the reported symptom (45 bookmarks do not add up across pages) points to an off-by-one in the page window. Fix it so pages are contiguous and complete, and add an optional, case-insensitive tag filter applied before paging, without changing the response for existing clients that do not send a tag.

**Changes**
| File | Change | Task |
|---|---|---|
| `bookmarks/api.py` | modified | T3 Add the tag filter to the store and the list endpoint |
| `bookmarks/store.py` | modified | T3 Add the tag filter to the store and the list endpoint |
| `docs/api.md` | modified | T5 Document the tag filter and the paging fix |
| `tests/test_pagination.py` | added | T2 Regression tests for paging |
| `tests/test_tag_filter.py` | added | T4 Tests for the tag filter |

**How it works**
1. Fix the paging off-by-one in BookmarkStore.list (coder)
2. Regression tests for paging (tester)
3. Tests for the tag filter (tester)
4. Document the tag filter and the paging fix (doc_writer)
5. Add the tag filter to the store and the list endpoint (coder)
6. Validate: full test suite (old + new), lint, contract, secrets (validator)

**Acceptance criteria**
- AC1: Paging through GET /bookmarks returns every bookmark exactly once; a full page has exactly `size` items.
- AC2: GET /bookmarks?tag=<t> returns only bookmarks having tag t, matched case-insensitively and exactly (not substring).
- AC3: With a tag filter, `total` counts matching bookmarks and paging applies to the filtered list.
- AC4: Requests without `tag` behave exactly as before (backward compatible); invalid paging values still return 422.
- AC5: Regression tests cover the paging bug; docs/api.md documents the tag filter.

### Additional Notes
**Assumptions / clarifications**
- Q1: Exact match, case-insensitive.
- Q2: Single tag only for now; out of scope.

Ticket #: REQ-202

## How to Validate Change
1. `pip install -e .[app,dev]`
2. `python -m pytest -q` from the repository root
3. Review the API contract in `api/openapi.yaml` (if present) against the endpoints

**Tested run:** `20261025-225054-c09277` (log: `.sdlc/runs/20261025-225054-c09277/events.jsonl`)
| Check | Result | Summary |
|---|---|---|
| syntax | ✅ Passed | all Python files compile |
| lint | ✅ Passed | ruff: no issues |
| unsafe-code | ✅ Passed | no unsafe patterns |
| security | ✅ Passed | bandit: no medium/high issues |
| dependencies | ⏭️ Skipped | set SDLC_DEPENDENCY_AUDIT=1 to audit |
| contract | ⏭️ Skipped | no API contract declared |
| tests | ✅ Passed | 17 passed |
| secrets | ✅ Passed | no secrets found |

## Potential Impact
- Clients that compensated for the missing item per page will now see one more item per page (correct behaviour, noted in docs changelog).
- Linear tag filtering over the in-memory store; acceptable at current size, needs an index with a database.

## Change Size
- [ ] **Major** - breaking change to API or behaviour
- [x] **Minor** - new backward-compatible capability
- [ ] **Patch** - fix or small tweak
- [ ] Documentation change

## How Has This Been Tested
- [x] Unit tests
- [ ] Integration tests
- [ ] Contract check
- [x] Lint / static analysis
- [x] Secret scan

| Test | Result |
|---|---|
| syntax | ✅ Passed - all Python files compile |
| lint | ✅ Passed - ruff: no issues |
| unsafe-code | ✅ Passed - no unsafe patterns |
| security | ✅ Passed - bandit: no medium/high issues |
| dependencies | ⏭️ Skipped - set SDLC_DEPENDENCY_AUDIT=1 to audit |
| contract | ⏭️ Skipped - no API contract declared |
| tests | ✅ Passed - 17 passed |
| secrets | ✅ Passed - no secrets found |

## Checklist
- [x] Code follows the project coding standards
- [x] Tests added for new behaviour and bug fixes
- [x] Documentation updated
- [x] No secrets or credentials in the change

## Reviewer
- [ ] Reviewed and approved by a human

<!-- title: REQ-202 - Fix bookmark paging and add tag filter -->
