# Phase 0 Research: Router Agent with Sentiment-Aware Refund Handoff

All items below were unresolved technical decisions (not spec-level ambiguities — those were already closed in `/speckit-clarify`). Each follows Decision / Rationale / Alternatives considered.

## 1. How to reach an LLM through OpenRouter from this codebase

**Decision**: Use `langchain_openai.ChatOpenAI`, already a project dependency, configured with `base_url="https://openrouter.ai/api/v1"` and `api_key` read from the `OPENROUTER_API_KEY` environment variable. Select the model via an `OPENROUTER_MODEL` environment variable with a small, cheap, structured-output-capable default (e.g. an `openai/*` model served through OpenRouter), so the exact model can be swapped without a code change.

**Rationale**: OpenRouter exposes an OpenAI-compatible Chat Completions API, and `langchain-openai` already supports pointing `ChatOpenAI` at an arbitrary `base_url`. This avoids adding a new HTTP client or SDK dependency (Constitution Principle III/Technology Constraints: don't add dependencies casually) while satisfying the explicit requirement to route calls through OpenRouter.

**Alternatives considered**: A raw `httpx`/`requests` call to OpenRouter's REST API directly — rejected because it would duplicate retry/streaming/structured-output handling `langchain-openai` already provides, and would add an unnecessary custom HTTP layer. `langchain-openai`'s dedicated OpenRouter partner package — not adopted because the project does not currently depend on it and the plain `ChatOpenAI(base_url=...)` pattern needs no new dependency.

## 2. How to get classification + sentiment in one deterministic shape

**Decision**: Define a small Pydantic model (`RouterDecision`) with `destination: Literal["order_support", "refund", "unclear"]` and `sentiment: Literal["positive", "neutral", "negative"]`, and call the LLM via `ChatOpenAI(...).with_structured_output(RouterDecision)`. The router node always requests both fields from the model in a single call — including when `destination` comes back `unclear` — then application code, not the model, enforces FR-004 by discarding the `sentiment` value from state whenever the *final* destination isn't `refund`. For a direct classification (`order_support`/`refund`) that happens in `router_agent` itself; for a classification that comes back `unclear`, `router_agent` carries the model's `sentiment` guess forward unresolved, and `clarify_intent` (§7) applies the same discard-or-keep rule once the customer's answer finalizes `destination`.

**Rationale**: A single structured-output call keeps the design simple (Principle III) and avoids two round-trips to the LLM. Enforcing "no sentiment for order/support" in plain code rather than relying on the model to omit the field is more reliable and trivially testable without mocking a conditional prompt.

**Alternatives considered**: Two separate LLM calls (one classify-only, a second sentiment-only call made only when refund is selected) — rejected for this feature as unnecessary complexity/latency for a single-call task; noted as a natural extension point if sentiment analysis later needs a different model or richer prompt than classification. Free-form text output parsed with regex/string matching — rejected as brittle compared to structured output support already available in `langchain-openai`.

## 3. LangGraph routing pattern for a router node fanning out to two placeholder nodes plus a clarification node

**Decision**: Build the graph with `langgraph.graph.StateGraph`, one node for the router (`router_agent`), one node for clarification (`clarify_intent`, see §7), and two terminal placeholder nodes (`order_support_agent`, `refund_agent`). Two conditional edges: `add_conditional_edges(router_agent, <path fn reading state["destination"]>, {"order_support": "order_support_agent", "refund": "refund_agent", "unclear": "clarify_intent"})`, and `add_conditional_edges(clarify_intent, <path fn reading state["destination"]>, {"order_support": "order_support_agent", "refund": "refund_agent"})` (only two branches here — `clarify_intent` never leaves `destination` as `"unclear"`). Both placeholder nodes route to `END`.

**Rationale**: This is the standard LangGraph pattern for a multi-condition fan-out and requires no custom control-flow abstraction beyond a second conditional edge, matching Principle III.

**Alternatives considered**: Modeling the two destinations as tool calls instead of graph nodes — rejected because the feature explicitly calls for two graph nodes ("placeholder node for the order/support agent and refund agent"), and CLAUDE.md's architecture describes them as agents/nodes, not tools. Giving `clarify_intent` its own `unclear`-shaped self-loop edge (routing back to itself on an unrecognized answer) instead of an internal re-ask loop via multiple `interrupt()` calls — rejected as an unnecessary extra edge/state transition for what `interrupt()` already handles within a single node (§7).

## 4. Verifying routing correctness with agent trajectory tests

**Decision**: Compile the graph with a checkpointer (`langgraph.checkpoint.memory.MemorySaver`) so per-step state history is retained. In integration tests, invoke the graph with a unique `thread_id` per case, then call `agentevals.graph_trajectory.utils.extract_langgraph_trajectory_from_thread(graph, config)` to get the actual node path, and assert it against a hand-written expected trajectory (e.g. `["router_agent", "order_support_agent"]` or `["router_agent", "refund_agent"]`) using `agentevals.graph_trajectory.strict.graph_trajectory_strict_match`. This directly implements User Story 3 / FR-010 / SC-001.

**Rationale**: `agentevals` (already a project dependency, chosen specifically for this purpose) ships exactly this extraction + strict-match pair for LangGraph graphs, requiring no custom trajectory-tracking code. A `MemorySaver` is the minimal checkpointer needed for `get_state_history` to work and needs no external storage (satisfies "Storage: N/A").

**Alternatives considered**: Manually instrumenting each node to append its name to a list in state and asserting on that list directly — rejected as a hand-rolled duplicate of what `agentevals` already provides, and the project already depends on `agentevals` for exactly this purpose.

## 5. CLI shape for Constitution Principle II compliance

**Decision**: Extend the existing `customer_support_fde:main` entry point to read a customer request either as a positional CLI argument or from stdin, invoke the compiled graph, and print the result: human-readable text by default, or JSON with a `--json` flag. On failure (FR-011), print an error to stderr and exit non-zero rather than printing a partial result.

**Rationale**: Satisfies Principle II's "text in/out protocol... via stdin/args... via stdout... via stderr" requirement with both JSON and human-readable formats, using only the standard library (`argparse`, `sys`, `json`) — no new dependency.

**Alternatives considered**: A dedicated CLI framework (e.g. `click`/`typer`) — rejected as unnecessary for a single command with one optional flag (Principle III), and not already a project dependency.

## 6. Sentiment/classification scope guardrails

**Decision**: The prompt instructs the model to assume English input and to classify into exactly one of three values: `order_support`, `refund`, or `unclear` — `unclear` covers both a request with no clear signal either way (FR-008) and a request that mixes both ordering/question and refund/complaint signals (FR-009). The model is always asked for a `sentiment` value in the same call regardless of which of the three destinations it returns (see §2); `router_agent` copies `sentiment` into state unconditionally at this point (not yet stripped — see §7) so it survives if `clarify_intent` later resolves the request to refund. If the model ever returns an unparseable/invalid `destination`, code maps it to `unclear` (routing to the clarifying question) rather than to a silent `order_support`/`refund` guess, consistent with FR-008/FR-009 now requiring the customer to be asked rather than defaulted; FR-011's "surface an error" continues to apply only to actual call failures, not to a low-confidence classification.

**Rationale**: Matches the revised spec requirements directly — no destination is silently assumed for ambiguous or mixed-signal input. Keeping `unclear` as a third first-class classification value (rather than post-hoc confidence-thresholding code) keeps the model's own judgment as the primary signal for the 90% accuracy target (SC-001) while giving code one unambiguous fallback path for anything it can't parse.

**Alternatives considered**: Keeping `destination` a strict two-value type and using a separate confidence score or heuristic to decide when to clarify — rejected as more moving parts than a third literal value for no behavioral benefit (Principle III). Silently defaulting unparseable model output to `order_support` as before — rejected because it reintroduces exactly the silent-guessing behavior FR-008/FR-009 now forbid.

## 7. Human-in-the-loop clarifying question without a second LLM call

**Decision**: Add a `clarify_intent` node, reached only when `router_agent` returns `destination == "unclear"`. It contains **no LLM call** — it presents a fixed, hardcoded three-choice question ("Are you placing an order, asking a general question, or requesting a refund?") via LangGraph's `interrupt()`, backed by the same `langgraph.checkpoint.memory.MemorySaver` checkpointer already required for trajectory-test extraction (§4), compiled with a stable `thread_id` for the run. The raw resumed value is matched deterministically in plain code against the three choices (order / question / refund); an unrecognized answer causes the node to call `interrupt()` again with the same question (multiple `interrupt()` calls in one node are supported — LangGraph replays the node from the top on each resume and matches resume values to `interrupt()` calls by the order they're encountered, so no state needs to be persisted across the retries beyond what the checkpointer already holds for the thread). Once a valid choice is received, `clarify_intent` sets `destination` to `order_support` or `refund` and applies the same state-shaping invariant as `router_agent`: `sentiment` is forwarded only when the resolved destination is `refund`, using the value `router_agent` already computed in its one LLM call — never a newly elicited or re-computed value (FR-013). This keeps the feature at exactly one LLM call per request, even when clarification is needed.

**Rationale**: `MemorySaver` is RAM-only and already a planned dependency, so this needs no new dependency and no persistent storage, satisfying "Storage: N/A". Splitting `clarify_intent` into its own node (rather than looping inside `router_agent`) means the `interrupt()` call has no LLM invocation before it in the same node body, so replay-on-resume is cheap and side-effect-free — the risk of re-running a paid, non-deterministic LLM call on every retry (which a single combined node would have) is avoided entirely. Naming it `clarify_intent` rather than `clarify_agent`/`*_agent` reflects that, unlike `router_agent` and the two downstream placeholders, it performs no agentic/LLM work — it's deterministic control flow.

**Alternatives considered**: A CLI-level re-prompt loop (the clarifying question and re-ask handled entirely in `cli.py`, outside the graph) — rejected because it would move routing-relevant control flow out of the graph, making it untestable via the same `agentevals` trajectory-match approach already used for the other two paths (User Story 4 / FR-010), and would duplicate the "what are the three valid choices" logic outside the state machine that owns `destination`. Re-eliciting sentiment from the customer directly as part of the clarifying question — rejected per FR-013 and the Clarifications session: the customer is asked at most one question (intent), never a second one about their emotional state. Putting the `interrupt()` call inside `router_agent` itself (one combined node) — rejected because replaying that node on resume would re-run the LLM classification call each time, adding latency/cost and a non-determinism risk on every retry of the clarifying question.

## Outcome

All unknowns from Technical Context are resolved. No `NEEDS CLARIFICATION` markers remain.
