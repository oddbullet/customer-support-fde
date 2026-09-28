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
- Conversation history condensation once a conversation grows past a token threshold, so long
  order/refund conversations stay within context.
- OpenTelemetry tracing via Arize Phoenix when a collector endpoint is configured.

A `.env` file is used for configuration, including the OpenRouter API key and model id (see
`.env.example`).

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
  continues without one, or signs up a new one; loads any stored preferences.
- **call_model** — the order/support agent. Answers menu and ingredient/allergy questions and
  manages the cart via tool calls; condenses older messages into a running summary once history
  grows too large. Its tool calls are guarded by the tool-call limit (see `tool_limit_node`).
- **order_tools** — tool node backing `call_model`: menu lookup, add/remove cart items, cart
  total, mark order confirmed.
- **await_customer** — interrupts to collect the customer's next reply during ordering, looping
  back to `call_model` until the order is confirmed.
- **cart_summary_node** — renders the confirmed cart into an order summary and records the order.
- **ticket_gen_node** — produces the final ticket artifact: an order ticket (order/support path)
  or a refund ticket (refund path).
- **memory_gen_node** — after an order, extracts and persists updated account preferences
  (likes, dislikes, allergies) from the conversation.
- **refund_agent** — the refund/complaints agent. Looks up the order, gathers the facts the
  refund policy needs, and calls tools to apply the policy or log a complaint. Its tool calls are
  guarded by the tool-call limit (see `tool_limit_node`).
- **refund_tools** — tool node backing `refund_agent`: `lookup_order`, `process_refund_request`,
  `log_complaint`, `conclude_refund_conversation`.
- **refund_await_customer** — interrupts to collect the customer's next reply during the refund
  conversation, looping back to `refund_agent` until resolved.
- **tool_limit_node** — ends the conversation when `call_model` or `refund_agent` asks for the
  same tool in more than 3 consecutive steps within one customer turn (a runaway tool loop). The
  tool is not run; the node records `{agent, tool}` in `tool_limit_reached`, and the CLI shows a
  red "please try again later" warning.

# Development

Write or modified the test first before writing the actual code. Use Test Driven Development.

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