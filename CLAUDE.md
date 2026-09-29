# Project Overview
An agentic customer support system for a Chinese restaurant, built as a LangGraph state machine
driven by an LLM (via OpenRouter). Features:

- Menu, ingredient, and allergy questions, answered from the SQLite-backed menu.
- Order placement: cart management (add/remove items, get cart/cart total) and order
  confirmation.
- Customer account identification (use an existing account, continue without one, or sign up),
  with a per-account free-text preferences memory (likes, dislikes, allergies) updated after
  every order.
- Post-order complaints and refund requests evaluated against restaurant refund policy
  (`refund_policy.py`), with sentiment-aware tone in the refund conversation.
- A generated support ticket (order ticket or refund ticket) for every resolved conversation,
  written to the `tickets/` directory.
- Conversation history condensation once a conversation grows past 40,000 tokens
  (`HISTORY_TOKEN_THRESHOLD`), so long order/refund conversations stay within context. At the
  start of a customer turn, everything but the last 3 messages (of any type; a tool result is
  never kept without the tool call before it) is folded into a running summary; the summarizer
  receives those messages as a plain-text transcript, not raw chat/tool messages. A failed or
  blank summary is retried once; if both attempts fail, the full history is kept for that turn.
  The order summary also feeds `memory_gen_node`, so preferences stated in condensed turns are
  still stored.
- OpenTelemetry tracing via Arize Phoenix when a collector endpoint is configured.
- Logging goes to Phoenix only: `setup_tracing()` always installs `PhoenixLogHandler`
  (`tracing.py`) on the root logger, which attaches each WARNING+ record (ours and libraries') to
  the current span as a `log` event, records any exception, and marks the span ERROR. Nothing is
  ever printed to the terminal; without a Phoenix endpoint, log records are dropped.
- LLM circuit breaker: after the primary model exhausts its retries, requests fall back to
  `FALLBACK_MODEL` for a 60-second cool-down, then a single-attempt probe tries the primary
  again; if both models fail, the CLI shows `MODEL_RETRY_PROMPT` and replays the failed step on
  Enter, up to `MODEL_RETRY_LIMIT` (2) times per step, then treats it as unrecoverable.
  Each LLM request attempt times out after 40 seconds (`LLM_TIMEOUT_SECONDS`).
- Workflow iteration limit: each `graph.invoke()` is capped at 100 graph steps
  (`WORKFLOW_ITERATION_LIMIT` in `interactive.py`, passed as LangGraph's `recursion_limit`).
  Hitting it is unrecoverable (see Failure handling).
- Transaction status: a placed order's recap starts "Your order has been placed." and ends with
  the Order ID and "Please show this ID when you pick up your order." A submitted refund names the
  amount, says it awaits staff review, and gives the Order ID.
- Failure handling:
  - Customer-facing texts live in `messages.py`. Technical details are only logged (→ Phoenix).
  - Unrecoverable failures (tool-call limit, iteration limit, models down after the manual
    retries, any store error or other exception escaping a conversation) are logged at ERROR and
    the CLI shows only `GENERIC_ERROR_MESSAGE` ("…Please exit the application and try again. If
    the problem continues, please order at the counter."), waits for Enter, and exits 1. If
    recording a confirmed order fails, `cart_summary_node` raises `OrderNotPlacedError` and the CLI
    shows `ORDER_NOT_PLACED_MESSAGE` instead.
  - Tool errors: an exception inside a tool is returned to the agent as an error `ToolMessage`
    carrying a fixed instruction (`TOOL_ERROR_MESSAGE`) to retry the same call without telling the
    customer; the real exception is only logged. Repeated failures end at the tool-call limit (see
    `tool_limit_node`). Invalid tool-call arguments return the validation message so the model can
    correct them.
  - Database errors: SQLite errors on both read and write paths surface as `OrderStoreError`.
    Refund tools log them and reply to the agent with `ORDER_LOOKUP_FAILED`,
    `REFUND_NOT_SUBMITTED`, or `COMPLAINT_NOT_RECORDED`. If a refund was saved but re-reading it
    fails, the tool still reports it submitted. A complaint-lookup failure while writing the
    refund ticket is logged and the ticket is written without a decision.
  - Broken menu database: at startup the CLI loads the menu; if the database or `menu_items`
    table is missing, it shows a red warning with the `uv run start --init-db` fix and exits 1.
  - Malformed router output (not matching `RouterDecision`) falls back to `unclear`, so
    `clarify_intent` asks the customer.

A `.env` file is used for configuration, including the OpenRouter API key, model id, and optional
fallback model id (see `.env.example`).

# Tech Stack
- Python 3.14
- LangGraph (+ LangChain / `langchain-openai` for the OpenRouter-backed LLM)
- SQLite (menu, orders, refund requests, complaints, accounts)
- Arize Phoenix (`arize-phoenix-otel`, OpenTelemetry tracing)
- Rich (interactive CLI rendering)
- PyTest (+ `agentevals` for LLM-judged end-to-end tests)

# Architecture
Each item below is a LangGraph node (see `src/customer_support_fde/graph.py`):

- **router_agent** — entry point for every message. Classifies the request as `order_support`,
  `refund`, or `unclear`, and separately assesses sentiment (surfaced only to the refund agent).
- **clarify_intent** — asks the customer to disambiguate when the router's destination is
  `unclear`, then routes to `order_support` or `refund`.
- **account_identification_node** — on the order/support path, identifies an existing account,
  continues without one, or signs up a new one; loads any stored preferences. An account "not
  found" shows a recovery menu; a database failure (`OrderStoreError`) propagates and stops the
  workflow (the CLI shows the generic error message and exits).
- **call_model** — the order/support agent. Answers menu and ingredient/allergy questions and
  manages the cart via tool calls; condenses older messages into a running summary once history
  grows too large. Its tool calls are guarded by the tool-call limit (see `tool_limit_node`).
- **order_tools** — tool node backing `call_model`: menu lookup, add/remove cart items, cart
  total, mark order confirmed. Tool exceptions go back to the agent via `handle_tool_error`
  (`nodes/common.py`).
- **await_customer** — interrupts to collect the customer's next reply during ordering, looping
  back to `call_model` until the order is confirmed.
- **cart_summary_node** — renders the confirmed cart into an order summary and records the order;
  a store failure while recording raises `OrderNotPlacedError`.
- **ticket_gen_node** — produces the final ticket artifact: an order ticket (order/support path)
  or a refund ticket (refund path).
- **memory_gen_node** — after an order, extracts and persists updated account preferences
  (likes, dislikes, allergies) from the conversation.
- **refund_agent** — the refund/complaints agent. Looks up the order, gathers the facts the
  refund policy needs, and calls tools to apply the policy or log a complaint. Its tool calls are
  guarded by the tool-call limit (see `tool_limit_node`).
- **refund_tools** — tool node backing `refund_agent`: `lookup_order`, `process_refund_request`,
  `log_complaint`, `conclude_refund_conversation`. Tool exceptions go back to the agent via
  `handle_tool_error` (`nodes/common.py`).
- **refund_await_customer** — interrupts to collect the customer's next reply during the refund
  conversation, looping back to `refund_agent` until resolved.
- **tool_limit_node** — ends the conversation when `call_model` or `refund_agent` asks for the
  same tool in more than 3 consecutive steps within one customer turn (a runaway tool loop). The
  tool is not run; the node logs and records `{agent, tool}` in `tool_limit_reached`, and the CLI
  shows the generic error message and exits.

Every model call made by these nodes goes through `build_llm()` in `nodes/common.py`. When
`FALLBACK_MODEL` is set, it returns a `CircuitBreakerLLM` (`circuit_breaker.py`) that shares one
in-process circuit across all agents and emits an `llm.circuit_breaker` trace span per request;
when both models fail it raises `ModelUnavailableError`, which `interactive.py` turns into the
retry prompt.

# Development

Write or modified the test first before writing the actual code. Use Test Driven Development.

Always ask before committing. No overengineering, keep things simple.

# Commands

Start an interactive conversation (initialize the database first — see Setup below):

```
uv run start
```

Run the unit and integration test suite (excludes end-to-end tests by default):

```
uv run pytest
```

Run the end-to-end tests, which call the real OpenRouter LLM and require `OPENROUTER_API_KEY`
and `LLM_JUDGE` to be set:

```
uv run pytest -m e2e
```

# Setup
The menu and confirmed orders live in a SQLite database, not `menu/menu.json` (which now only
serves as seed data). Before running any conversation, initialize and seed the database:

```
uv run start --init-db
```

This is idempotent and safe to re-run after editing `menu.json` — it updates existing dishes and
inserts new ones without deleting anything. The database path defaults to `customer_support.db` in
the working directory, overridable via `CUSTOMER_SUPPORT_DB`.

Re-run `--init-db` on an existing database too: it also creates the `refund_requests`,
`refund_request_lines`, `complaints`, and `accounts` tables used by the refund agent and the
customer account identification node, and is safe to run against a database that already has
orders in it.

To inspect the compiled LangGraph topology, run:

```
uv run start --graph
```

This renders the current graph as a PNG to `graph.png` in the working directory. Rendering is
done via the public Mermaid.ink API, so this requires internet access.