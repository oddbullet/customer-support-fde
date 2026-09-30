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
  written to the `tickets/` directory. Refund tickets are named `refund-<order_id>-<8 hex>.md` so a
  later conversation about the same order never overwrites an earlier ticket; a blank issue or
  sentiment renders as its default (`Not recorded` / `unavailable`).
- Customer input: the CLI skips blank or spaces-only lines and refuses lines over 1,000
  characters (`MAX_INPUT_CHARS`, shows `INPUT_TOO_LONG`) at every prompt, so neither reaches the
  graph; end of input exits like `/exit`. `log_complaint` and `process_refund_request` reject a
  blank complaint/issue argument, so the model is told to fix it.
- PII redaction: every accepted customer line is passed through `pii.redact()` (Presidio, small
  spaCy model) before it reaches the graph, so the LLM, Phoenix traces, tickets and stored
  preferences never see it. Only pattern-based entities are replaced (`<EMAIL_ADDRESS>`,
  `<PHONE_NUMBER>`, `<CREDIT_CARD>`, `<US_SSN>`, `<IBAN_CODE>`, `<IP_ADDRESS>`); names, places and
  dates are not, so dish names and pickup times survive. A redaction error is unrecoverable
  (`GENERIC_ERROR_MESSAGE`).
- Conversation history condensation once a conversation grows past 40,000 tokens
  (`HISTORY_TOKEN_THRESHOLD`), so long order/refund conversations stay within context. At the
  start of a customer turn, everything but the last 3 messages (of any type; a tool result is
  never kept without the tool call before it) is folded into a running summary; the summarizer
  receives those messages as a plain-text transcript, not raw chat/tool messages. A failed or
  blank summary is retried once; if both attempts fail, the full history is kept for that turn.
  The order summary also feeds `memory_gen_model`, so preferences stated in condensed turns are
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
  Each LLM request attempt times out after 40 seconds (`LLM_TIMEOUT_SECONDS`) and is capped at
  4,000 output tokens (`LLM_MAX_OUTPUT_TOKENS`), since the timeout alone doesn't stop a runaway
  generation that keeps streaming.
- Workflow iteration limit: each `graph.invoke()` is capped at 100 graph steps
  (`WORKFLOW_ITERATION_LIMIT` in `interactive.py`, passed as LangGraph's `recursion_limit`).
  Hitting it is unrecoverable (see Failure handling).
- Transaction status: a placed order's recap starts "Your order has been placed.", shows a
  `Placed:` local time after the total, and ends with the Order ID and "Please show this ID when you
  pick up your order." A submitted refund names the amount, says it awaits staff review, gives the
  Order ID, and shows a `Submitted:` local time.
- Date & time: every stored timestamp (orders, refunds, complaints, accounts) and the refund
  check's "now" come from an NTP server (`clock.trusted_now()`, `time.windows.com`), never the host
  clock; an order or refund uses one reading for what it stores and shows. Times are
  stored and compared in UTC. The restaurant timezone (a main US zone, stored in the
  `restaurant_settings` table, loaded once by `restaurant_time.load()`) is used only for display
  (`restaurant_time.format_local()`). A `created_at` that is in the future, malformed, empty,
  missing, or has no timezone is auto-rejected by `refund_policy.evaluate()` as
  `invalid_order_date` (customer is sent to staff; the tool logs a WARNING).
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
    `tool_limit_function`). Invalid tool-call arguments return the validation message so the model can
    correct them.
  - Database errors: SQLite errors on both read and write paths surface as `OrderStoreError`.
    Refund tools log them and reply to the agent with `ORDER_LOOKUP_FAILED`,
    `REFUND_NOT_SUBMITTED`, or `COMPLAINT_NOT_RECORDED`. If a refund was saved but re-reading it
    fails, the tool still reports it submitted. A complaint-lookup failure while writing the
    refund ticket is logged and the ticket is written without a decision.
  - Broken menu database: at startup the CLI loads the menu; if the database or `menu_items`
    table is missing, it shows a red warning with the `uv run start --init-db` fix and exits 1.
  - Restaurant timezone not set (or unsupported): at startup, a red warning with the
    `uv run start --set-tz <zone>` fix, exit 1.
  - Time server unreachable (`ClockUnavailableError`): while placing an order →
    `OrderNotPlacedError` (`ORDER_NOT_PLACED_MESSAGE`); inside a refund tool, `handle_tool_error`
    re-raises it instead of asking the agent to retry → `GENERIC_ERROR_MESSAGE`; anywhere else
    (account sign-up, complaints) it escapes the conversation → `GENERIC_ERROR_MESSAGE`. All exit 1.
  - Malformed router output (not matching `RouterDecision`) falls back to `unclear`, so
    `clarify_intent_function` asks the customer.

A `.env` file is used for configuration, including the OpenRouter API key, model id, and optional
fallback model id (see `.env.example`).

# Tech Stack
- Python 3.14
- LangGraph (+ LangChain / `langchain-openai` for the OpenRouter-backed LLM)
- SQLite (menu, orders, refund requests, complaints, accounts, restaurant settings)
- `ntplib` (trusted time) and `tzdata` (timezone data for `zoneinfo` on Windows)
- Presidio + spaCy `en_core_web_sm` (PII redaction of customer input)
- Arize Phoenix (`arize-phoenix-otel`, OpenTelemetry tracing)
- Rich (interactive CLI rendering)
- PyTest (+ `agentevals` for LLM-judged end-to-end tests)

# Architecture
Each item below is a LangGraph node (see `src/customer_support_fde/graph.py`). Node names end
in `_agent` (LLM + tools, AI), `_model` (single LLM call, AI), or `_function` (plain code, no AI);
the Python functions keep their own names (shown in parentheses). Full per-component docs and the
icon diagram: `docs/ARCHITECTURE.md` — keep it in sync when the graph changes.

- **router_model** (`router_agent`) — entry point for every message. Classifies the request as
  `order_support`, `refund`, or `unclear`, and separately assesses sentiment (surfaced only to the
  refund agent).
- **clarify_intent_function** (`clarify_intent`) — asks the customer to disambiguate when the
  router's destination is `unclear`, then routes to `order_support` or `refund`.
- **account_identification_function** (`account_identification_node`) — on the order/support
  path, identifies an existing account, continues without one, or signs up a new one; loads any
  stored preferences. An account "not found" shows a recovery menu; a database failure
  (`OrderStoreError`) propagates and stops the workflow (the CLI shows the generic error message
  and exits).
- **order_agent** (`call_model`) — the order/support agent. Answers menu and ingredient/allergy
  questions and manages the cart via tool calls; condenses older messages into a running summary
  once history grows too large. Its tool calls are guarded by the tool-call limit (see
  `tool_limit_function`).
- **order_tools_function** (`order_tools`) — tool node backing `order_agent`: menu lookup,
  add/remove cart items, cart total, mark order confirmed. Tool exceptions go back to the agent
  via `handle_tool_error` (`nodes/common.py`).
- **order_await_customer_function** (`await_customer`) — interrupts to collect the customer's next
  reply during ordering, looping back to `order_agent` until the order is confirmed.
- **cart_summary_function** (`cart_summary_node`) — renders the confirmed cart into an order
  summary and records the order; a store failure while recording raises `OrderNotPlacedError`.
- **ticket_gen_model** (`ticket_gen_node`) — produces the final ticket artifact: an order ticket
  (order/support path, no LLM) or a refund ticket (refund path; the LLM extracts the issue).
- **memory_gen_model** (`memory_gen_node`) — after an order, extracts and persists updated account
  preferences (likes, dislikes, allergies) from the conversation.
- **refund_agent** (`refund_agent`) — the refund/complaints agent. Looks up the order, gathers the
  facts the refund policy needs, and calls tools to apply the policy or log a complaint. Its tool
  calls are guarded by the tool-call limit (see `tool_limit_function`).
- **refund_tools_function** (`refund_tools`) — tool node backing `refund_agent`: `lookup_order`,
  `process_refund_request`, `log_complaint`, `conclude_refund_conversation`. Tool exceptions go
  back to the agent via `handle_tool_error` (`nodes/common.py`).
- **refund_await_customer_function** (`refund_await_customer`) — interrupts to collect the
  customer's next reply during the refund conversation, looping back to `refund_agent` until
  resolved.
- **tool_limit_function** (`tool_limit_node`) — ends the conversation when `order_agent` or
  `refund_agent` asks for the same tool in more than 3 consecutive steps within one customer turn
  (a runaway tool loop). The tool is not run; the node logs and records `{agent, tool}` in
  `tool_limit_reached`, and the CLI shows the generic error message and exits.

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

Set the restaurant timezone once (`eastern`, `central`, `mountain`, `arizona`, `pacific`,
`alaska`, or `hawaii`); `--init-db` creates the `restaurant_settings` table it is stored in:

```
uv run start --set-tz eastern
```

Tests never reach the real NTP server: the unit/integration `conftest.py` files replace
`clock.trusted_now` with the local clock and set a timezone. The e2e tests use real NTP.

To inspect the compiled LangGraph topology, run:

```
uv run start --graph
```

This renders the current graph as a PNG to `graph.png` in the working directory. Rendering is
done via the public Mermaid.ink API, so this requires internet access.