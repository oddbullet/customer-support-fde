# Quickstart: Validating the Test Case Audit

This guide is for confirming the audit was done correctly once implementation
(`/speckit-tasks` → `/speckit-implement`) is complete. It does not include the audit
methodology itself (see `research.md`) or the artifact structure (see `data-model.md`).

## Prerequisites

- Repository checked out with the audit's changes applied (branch `009-test-case-audit` or
  wherever the work landed).
- Python >=3.14 environment with project dependencies installed (`pytest`, `langgraph`,
  `langchain`, etc. — per `pyproject.toml`).

## 1. Confirm the test count did not increase (SC-003)

```bash
pytest --collect-only -q | tail -1
```

Compare against the `baseline_test_count` recorded in
`specs/009-test-case-audit/audit-record.md`. The number reported here must be **less than
or equal to** that baseline.

## 2. Confirm the full suite passes (FR-010)

```bash
pytest -q
```

Expect no failures. Note the reported run time and compare it against
`audit-record.md`'s `baseline_runtime` — it should be the same or better (SC-007).

## 3. Confirm every in-scope tool and node has base + edge coverage (SC-001)

Open `specs/009-test-case-audit/audit-record.md` and check the coverage matrix: every row
(the 10 tools in `tools/cart_tools.py`, `tools/menu_tools.py`, `tools/refund_tools.py`, and
the 9 node functions across `nodes/*.py` — see `research.md` Decision 2 for the exact list)
must show both `has_base_test` and `has_edge_test` as true.

Spot-check one row directly, e.g. for `mark_order_confirmed`:

```bash
pytest tests/unit/test_cart_tools.py -k mark_order_confirmed -v
```

Confirm the listed test names/comments include at least one `(base)` and one `(edge)` case.

## 4. Confirm every retained/added test carries a category comment (SC-006)

Spot-check a file for tests missing a tag comment (should return nothing):

```bash
grep -B1 "^def test_\|^async def test_" tests/unit/test_cart_tools.py | grep -B1 "^def test_" | grep -v "(base)\|(edge)\|(error)\|(regression)\|^def test_\|^--"
```

(This is a spot-check, not exhaustive — `audit-record.md` is the authoritative record that
every test case was checked.)

## 5. Confirm no full end-to-end/multi-agent test was introduced (SC-005, FR-006)

```bash
git diff main...009-test-case-audit --stat -- tests/
```

Confirm no new test file spans router → order/refund agent → ticket summary in one flow;
only edits to the existing `tests/unit/*.py` and `tests/integration/*_trajectory.py` files
(each already scoped to a single agent) plus the new `audit-record.md` should appear.

## 6. Confirm removed tests are traceable (SC-004)

Pick any entry in `audit-record.md`'s `removed` list. Without looking at the git diff,
confirm you can identify:
- Which test was removed (its pytest node id).
- Which retained test supersedes it.
- Why (the one-line rationale).

If a person unfamiliar with the audit can do this from the record alone, SC-004 is met.
