# Feature Specification: Test Case Audit & Coverage Rationalization

**Feature Branch**: `009-test-case-audit`

**Created**: 2026-09-12

**Status**: Draft

**Input**: User description: "I want you to review every single test case to ensure that we actually need them. We have over 100+ test cases. We should test every tool and node. We can do an end to end test but not in this scope, we wait until the project is at the end stage for that. For test cases, we need to test base case, and edge case. We don't need redundant test cases."

## Clarifications

### Session 2026-09-12

- Q: Should this audit actually edit the test files (delete redundant tests, add missing base/edge tests) as part of the deliverable, or just produce a report recommending those changes for someone to apply later? → A: Audit applies changes directly — it removes confirmed-redundant tests and adds missing base/edge tests in the test files itself, going through normal PR review, rather than only recommending changes for a separate follow-up.
- Q: Where should the audit's output record (the before/after test counts, removal rationales, and closed gaps) live so a future reviewer can find it? → A: A checked-in markdown file in the repo, at `specs/009-test-case-audit/audit-record.md`.
- Q: For the "100% of tools and nodes have base + edge coverage" requirement, which modules count as an in-scope "tool" or "node"? → A: Only the tool functions in `src/customer_support_fde/tools/` and the graph nodes in `src/customer_support_fde/nodes/` — not their dependencies (e.g., `db.py`, `refund_policy.py`) or the CLI/graph wiring.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Eliminate redundant test cases without losing coverage (Priority: P1)

As a maintainer of the customer support agent system, I want the existing 100+ test cases reviewed so that duplicate or overlapping tests are removed, keeping the suite fast and easy to reason about without silently dropping any unique behavioral coverage.

**Why this priority**: A bloated, partially-redundant suite slows every future change (slower CI, more noise in reviews) and makes it harder to tell which tests actually protect the system. This is the core pain point driving the request and delivers value the moment it's done, independent of any other work.

**Independent Test**: Can be fully tested by producing a before/after inventory of test cases per module, confirming every removed test's assertion is demonstrably duplicated by a retained test, and confirming the full suite still passes after removal.

**Acceptance Scenarios**:

1. **Given** two or more test cases that exercise the same code path and assert the same outcome, **When** the audit reviews them, **Then** all but one are removed from the test files, with a documented reason (in the audit record) referencing the retained test that already covers that behavior.
2. **Given** a test case that is the only coverage for a specific error condition, boundary value, or regression guard, **When** the audit reviews it, **Then** it is retained even if it superficially resembles another test.
3. **Given** the audit's redundant-test removals have been made, **When** the full test suite is run, **Then** it passes with no reduction in the set of distinct behaviors verified.

---

### User Story 2 - Guarantee base-case and edge-case coverage for every tool and node (Priority: P2)

As a maintainer, I want every tool function and every LangGraph node in the system confirmed to have at least one base-case (happy path) test and at least one edge-case (boundary/unusual input) test, so that coverage gaps are found and closed before they cause a production incident.

**Why this priority**: Removing redundancy (P1) is only safe and valuable if the resulting suite still fully covers the system; this story is what proves the suite is sufficient, not just smaller.

**Independent Test**: Can be fully tested by producing a coverage matrix listing every tool and node against "has base-case test" and "has edge-case test," and confirming no row is missing either column after the audit.

**Acceptance Scenarios**:

1. **Given** a tool or node with no existing edge-case test, **When** the audit reviews it, **Then** the gap is flagged and a new edge-case test is added before the audit is considered complete.
2. **Given** a tool or node with no existing base-case test, **When** the audit reviews it, **Then** the gap is flagged and a new base-case test is added before the audit is considered complete.
3. **Given** a tool or node that already has both a base-case and an edge-case test, **When** the audit reviews it, **Then** no new test is added for it solely to satisfy this story.

---

### User Story 3 - Produce a reviewable audit record (Priority: P3)

As a reviewer (or a future contributor), I want a record of what was removed, what was added, and why, so I can verify the audit's decisions without having to re-derive the reasoning from a raw diff.

**Why this priority**: This makes the outcome of Stories 1 and 2 trustworthy and reviewable, but the audit still delivers its core value (a leaner, fully-covered suite) even before this record exists.

**Independent Test**: Can be fully tested by handing the audit record to someone unfamiliar with the work and confirming they can correctly explain, for any given test case, whether it was kept, removed, or added, and why.

**Acceptance Scenarios**:

1. **Given** the audit is complete, **When** a reviewer opens the audit record, **Then** it lists, per module, the test case count before and after, every removed test with its rationale, and every added test with the gap it closes.
2. **Given** a removed test case, **When** a reviewer inspects the record, **Then** they can identify which retained test case makes the removed one redundant.

---

### Edge Cases

- What happens when a single test function is parametrized into several cases, some of which are redundant and some of which are not? (Each parametrized instance is treated as its own distinct test case for the purposes of this audit, not the enclosing function.)
- How does the audit handle a tool or node whose only existing tests are indirect (exercised only through an agent-level or trajectory-level test, not a direct unit test)? Such coverage counts only if the base/edge distinction is still verifiable from that test; otherwise a direct test is added.
- What happens when two tests look similar (same tool, same kind of input) but assert different outcomes or different fields of the result? They are not considered redundant — divergent assertions mean divergent coverage even for similar inputs.
- How does the audit treat existing tests that fail or are already skipped/xfail at the time of review? They are flagged separately in the audit record rather than folded into the redundancy/coverage changes, since a broken test cannot be judged as redundant coverage.
- What happens if a tool or node has more than one plausible "edge case" (e.g., empty input, invalid ID, boundary quantity)? At least one edge-case test is required; additional edge-case tests are retained only if they are not redundant with each other per Story 1.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The audit MUST catalog every existing test case in the suite — including each individual parametrized instance — and map each one to the specific tool, node, or module it exercises.
- **FR-002**: For every tool function under `src/customer_support_fde/tools/` and every graph node under `src/customer_support_fde/nodes/`, the audit MUST confirm at least one base-case (happy path) test and at least one edge-case (boundary/unusual input) test exist. Modules those tools/nodes depend on (e.g., `db.py`, `refund_policy.py`) and the CLI/graph wiring (`cli.py`, `graph.py`) are out of scope for this coverage guarantee.
- **FR-003**: Where a tool or node is missing a base-case or edge-case test, the audit MUST add the missing test case(s) so that every tool and node satisfies FR-002.
- **FR-004**: The audit MUST identify redundant test cases — cases whose assertions and exercised code path are already fully covered by another retained test case — and MUST remove them from the test files.
- **FR-005**: The audit MUST NOT remove any test case that is the sole coverage for a distinct behavior, error condition, boundary value, or regression guard, regardless of superficial similarity to another test.
- **FR-006**: The audit's scope MUST exclude authoring any new full end-to-end (multi-agent, full-pipeline) test; that work is explicitly deferred to a later project stage.
- **FR-007**: Every test case retained or newly added as a result of this audit MUST carry the one-line category comment (e.g., base/edge/error/regression) required by the project's testing standards.
- **FR-008**: The audit MUST NOT change the assertions or pass/fail behavior of any retained test case as a side effect of the review; only removal of redundant cases and addition of missing base/edge cases is in scope.
- **FR-009**: The audit MUST produce a checked-in markdown record, at `specs/009-test-case-audit/audit-record.md`, enumerating per tool/node/module: the test case count before and after the audit, each removed test with the rationale and the retained test that makes it redundant, and each added test with the coverage gap it closes.
- **FR-010**: After the audit is applied, the full test suite MUST pass.

### Key Entities

- **Test Case**: An individual executable test — one pytest function, or one instance of a parametrized test — with attributes: the tool/node/module it targets, its category (base/edge/error/regression), and its audit outcome (kept, removed, or added).
- **Tool/Node**: A unit of system behavior available for testing — a tool function invoked by an agent, or a node in the conversation graph — with attributes: name, owning module, and its current base/edge test coverage status.
- **Audit Record**: The output artifact of this feature — a checked-in markdown file (`specs/009-test-case-audit/audit-record.md`) containing a coverage matrix (tool/node × base-case-present × edge-case-present) plus a list of removed test cases (each with its rationale and the test that supersedes it) and a list of added test cases (each with the gap it closes).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of tools and nodes in the system have at least one base-case test and at least one edge-case test after the audit.
- **SC-002**: Every test case removed during the audit is one whose behavioral coverage is demonstrably duplicated by a retained test case, with zero unique behaviors losing coverage.
- **SC-003**: The total test case count after the audit is no higher than before it, reflecting removal of confirmed redundancy.
- **SC-004**: A person unfamiliar with the audit can determine, using only the audit record, why any specific test was removed or added, without inspecting the raw code diff.
- **SC-005**: No full end-to-end/multi-agent pipeline test is introduced as part of this effort.
- **SC-006**: 100% of test cases in the suite after the audit carry the required category comment/tag.
- **SC-007**: The full test suite passes after the audit is applied, with the same or better overall run time than before.

## Assumptions

- "Test case" means each individually executed test — including every distinct instance produced by `@pytest.mark.parametrize` — not just the enclosing function definition.
- "Every tool and node" is scoped precisely to the tool functions under `src/customer_support_fde/tools/` and the graph nodes under `src/customer_support_fde/nodes/`. Modules they depend on (e.g., `db.py`, `refund_policy.py`) and the CLI/graph wiring (`cli.py`, `graph.py`) are not required to individually satisfy the base+edge coverage guarantee, though existing tests for them are still included in the redundancy review (FR-001, FR-004).
- The existing per-agent trajectory/integration tests already in the suite are in scope for the redundancy review, but they are distinct from "end-to-end" in the sense excluded here: this audit does not add a new full-pipeline test spanning router → order/refund → ticket summary; that remains deferred to a later project stage as the user specified.
- Redundancy is judged by duplicated code-path-and-assertion coverage, not by superficial similarity in test names or fixtures.
- Determining "redundant" vs. "sole coverage" requires judgment; where it is ambiguous whether two tests are truly redundant, the default is to retain both rather than risk losing coverage.
- Test removal and addition resulting from this audit still go through the project's normal pull request review process; this spec does not change that workflow.
