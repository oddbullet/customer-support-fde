<!--
Sync Impact Report
- Version change: 1.0.0 → 1.1.0
- Modified principles:
  - IV. Observability & Versioning — observability mechanism changed from console/structured
    stdout+stderr logging to LangSmith-based logging and tracing for agent behavior
- Added sections: none
- Removed sections: none
- Deferred TODOs: none
-->

# Customer Support FDE Constitution

## Core Principles

### I. Test-First (NON-NEGOTIABLE)
Tests MUST be written before implementation for every feature or bug fix: write the test,
get it reviewed/approved, watch it fail, then implement until it passes (red-green-refactor).
No implementation commit MAY land without a corresponding failing-then-passing test.
Rationale: this project handles customer-support-facing logic where silent regressions
directly harm end users; enforcing test-first prevents unverified behavior from ever
reaching main.

### II. Library-First & CLI Interface
Every feature MUST start as a standalone, importable module under `src/customer_support_fde/`
with a clear, single purpose — no module MAY exist purely for organizational grouping.
Functionality that a human or script needs to invoke directly MUST be exposed through a CLI
entry point following a text in/out protocol: input via stdin/args, output via stdout, errors
via stderr, with both JSON and human-readable output formats supported where practical.
Rationale: a library-first, CLI-exposed design keeps logic independently testable and
scriptable, and avoids hidden coupling to any single runtime or framework.

### III. Simplicity (YAGNI)
Implementations MUST start with the simplest design that satisfies the current requirement.
Speculative abstractions, configuration options, or extensibility hooks for hypothetical
future needs MUST NOT be added. Added complexity (a new layer, dependency, or pattern) MUST
be justified in the PR/commit description by a concrete, current requirement it solves.
Rationale: this project is an early-stage scaffold; premature structure slows every
subsequent change more than it helps.

### IV. Observability & Versioning
Agent runs, tool calls, and errors MUST be logged and traced via LangSmith rather than raw
console/stdout output — every agent invocation MUST produce a LangSmith trace sufficient to
debug a failure without reproducing it locally. CLI error output MAY still go to stderr for
immediate operator feedback, but MUST NOT be the sole record of agent behavior. The project
MUST follow semantic versioning (MAJOR.MINOR.PATCH): MAJOR for breaking behavior/API changes,
MINOR for backward-compatible feature additions, PATCH for fixes and clarifications. Breaking
changes MUST be called out explicitly in the change description.
Rationale: agent behavior (prompts, tool calls, intermediate reasoning) is not adequately
captured by flat console logs; centralized tracing in LangSmith is required to debug,
evaluate, and audit agent runs, and disciplined versioning keeps consumers of the package
safe from silent breakage.

## Technology Constraints

The project targets Python >=3.14 and is packaged with the `uv_build` backend (see
`pyproject.toml`). New dependencies MUST be added deliberately and only when the standard
library or an existing dependency cannot reasonably satisfy the need. LangSmith (and its
client SDK) is a required dependency for agent observability per Principle IV; beyond it,
dependencies MUST NOT be added casually.

## Development Workflow

All changes MUST go through a pull request that: (1) links the failing test(s) added under
Principle I, (2) states which principle(s) are relevant to the change, and (3) calls out any
added complexity per Principle III with justification. Reviews MUST verify the PR does not
violate any Core Principle before approval; violations MUST be fixed or explicitly justified
in the PR description before merge.

## Governance

This constitution supersedes any conflicting team practice or prior informal convention.
Amendments require: (1) a documented rationale for the change, (2) an update to this file
following the Sync Impact Report format at the top of this document, and (3) a version bump
per semantic versioning — MAJOR for backward-incompatible governance/principle changes or
removals, MINOR for new principles or materially expanded guidance, PATCH for wording or
clarification-only edits. All PRs and reviews MUST verify compliance with this constitution;
any complexity that conflicts with Principle III MUST be justified in writing in the PR.
Runtime development guidance beyond this constitution belongs in `CLAUDE.md` or equivalent
agent guidance files, not here.

**Version**: 1.1.0 | **Ratified**: 2026-09-09 | **Last Amended**: 2026-09-09
