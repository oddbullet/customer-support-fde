# Customer Support FDE

An agentic customer support system for a Chinese restaurant. It answers menu and
ingredient/allergy questions, takes orders, and handles post-order complaints and refund
requests, producing a support ticket for every resolved conversation.

## Overview

The assistant runs as a LangGraph state machine driven by an LLM (via OpenRouter). A router
classifies each incoming message and hands it off to the order/support flow or the refund flow;
each flow uses tool-calling to look up the menu, manage the cart, or process refunds against
restaurant policy. Conversations are interactive (CLI, `rich`-rendered) and every resolved
conversation ends with a generated ticket and, for identified accounts, an updated preferences
memory.

Features:

- **Ordering** — menu, ingredient and allergy questions answered from the SQLite menu; add/remove
  cart items, cart total, order confirmation. A placed order shows its total, a `Placed:` time and
  an Order ID to show at pickup.
- **Accounts** — use an existing account, continue as a guest, or sign up. Each account keeps a
  free-text preferences memory (likes, dislikes, allergies), updated after every order.
- **Refunds and complaints** — the refund agent looks up the order and gathers the facts; the
  refund decision and amount come from code (`refund_policy.py`), never the LLM. Tone adapts to
  the customer's sentiment.
- **Tickets** — every resolved conversation writes an order or refund ticket to `tickets/`.
- **PII redaction** — emails, phone numbers, card numbers, SSNs, IBANs and IP addresses are
  replaced with placeholders (Presidio) before the input reaches the graph, so the LLM, traces,
  tickets and stored preferences never see them.
- **Long conversations** — once history passes 40,000 tokens, older messages are condensed into a
  running summary.
- **Reliability** — each LLM request times out after 40 seconds and is capped at 4,000 output
  tokens. With `FALLBACK_MODEL` set, a circuit breaker switches to the fallback model when the
  primary fails. A runaway tool loop (same tool more than 3 steps in a row) or more than 100 graph
  steps ends the conversation.
- **Trusted time** — every stored timestamp comes from an NTP server, not the computer's clock.
  Times are stored in UTC and shown in the restaurant's timezone.
- **Tracing** — Arize Phoenix (OpenTelemetry) traces every node and LLM call when a collector
  endpoint is configured. Warnings and errors are logged to Phoenix only, never the terminal.

Prompt injection attempts are redacted by OpenRouter before the prompt reaches the model. This
is set up in OpenRouter, not in this codebase.

## Architecture

```
customer message ─► router_model ─┬─ order_support ─► ORDER PATH
                                  ├─ refund ────────► REFUND PATH
                                  └─ unclear ───────► clarify_intent_function ─► ORDER or REFUND PATH

ORDER PATH
  account_identification_function
    ─► order_agent ⇄ order_tools_function            (menu, cart)
       order_agent ⇄ order_await_customer_function   (until the order is confirmed)
    ─► cart_summary_function ─┬─► ticket_gen_model   (order ticket)
                              └─► memory_gen_model   (update account preferences)

REFUND PATH
  refund_agent ⇄ refund_tools_function               (lookup, refund, complaint)
  refund_agent ⇄ refund_await_customer_function      (until resolved)
    ─► ticket_gen_model                              (refund ticket)

Either agent stuck in a tool loop ─► tool_limit_function ─► end
```

Node names end in `_agent` (LLM with tools), `_model` (a single LLM call) or `_function` (plain
code, no AI). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full workflow diagram and
what each node does.

## Prerequisites

- Python 3.14 (see `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) for dependency management and running the project
- An [OpenRouter](https://openrouter.ai/) API key
- Internet access: for LLM calls, the NTP time server (`time.windows.com`, UDP port 123), and
  `--graph` (renders via the Mermaid.ink API)

## Installation

```bash
git clone https://github.com/oddbullet/customer-support-fde
cd customer-support-fde
uv sync
```

`uv sync` creates a virtual environment and installs all dependencies from `pyproject.toml` /
`uv.lock`.

## Dependencies

Declared in `pyproject.toml` (exact versions pinned in `uv.lock`):

| Package | Used for |
|---|---|
| `langgraph` | The support workflow's state machine (nodes, edges, interrupts). |
| `langchain` | Messages, tools, and structured-output helpers used by the agents. |
| `langchain-openai` | LLM client pointed at OpenRouter. |
| `pydantic` | Tool arguments and structured-output schemas. |
| `presidio` | PII redaction of customer input. |
| `en-core-web-sm` | Small spaCy English model used by Presidio. |
| `ntplib` | Trusted current time from an NTP server. |
| `tzdata` | Timezone data for `zoneinfo` (needed on Windows). |
| `rich` | Interactive CLI rendering. |
| `python-dotenv` | Loads configuration from `.env`. |
| `arize-phoenix-otel` | OpenTelemetry tracing to Arize Phoenix. |
| `openinference-instrumentation-langchain` | Traces LangChain/LangGraph calls as spans. |
| `pytest` | Test runner. |
| `agentevals` | LLM-judged checks in the end-to-end tests. |

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | API key used to call the LLM through OpenRouter. |
| `OPENROUTER_MODEL` | No | OpenRouter model id. Defaults to `openai/gpt-4o-mini`. |
| `FALLBACK_MODEL` | No | Model used by the circuit breaker when the primary model fails. Leave blank to disable. |
| `LLM_JUDGE` | For e2e tests | Model id used as an LLM judge in end-to-end tests. |
| `PHOENIX_COLLECTOR_ENDPOINT` | No | Enables Arize Phoenix tracing when set. |
| `PHOENIX_PROJECT_NAME` | No | Phoenix project name. Defaults to `customer-support-fde`. |
| `CUSTOMER_SUPPORT_DB` | No | Path to the SQLite database file. Defaults to `customer_support.db`. |
| `CUSTOMER_SUPPORT_TICKETS_DIR` | No | Directory tickets are written to. Defaults to `tickets/`. |

## Running the application

The menu, orders, refunds, complaints and accounts live in a SQLite database (`menu/menu.json` is
only seed data). Before running any conversation, initialize and seed the database:

```bash
uv run start --init-db
```

This is idempotent and safe to re-run after editing `menu.json` — it updates existing dishes,
inserts new ones, and creates any missing tables without deleting anything.

Set the restaurant's timezone once (stored in the database; one of `eastern`, `central`,
`mountain`, `arizona`, `pacific`, `alaska`, `hawaii`). Every time shown to customers and the
agent is converted to it; storage and the refund window stay in UTC:

```bash
uv run start --set-tz eastern
```

Then start an interactive conversation:

```bash
uv run start
```

Type a question, an order, or a refund request; `/exit` or Ctrl+C quits. Blank lines are skipped
and lines over 1,000 characters are refused. If the menu database or the timezone is missing, the
app shows a red warning with the command that fixes it and exits.

To inspect the compiled LangGraph topology as a PNG (requires internet access, rendered via the
Mermaid.ink API):

```bash
uv run start --graph
```

This writes `graph.png` to the working directory.

## Testing

This project follows test-driven development (tests are written before implementation).

Run the unit and integration test suite (excludes end-to-end tests by default):

```bash
uv run pytest
```

Unit and integration tests never reach the real NTP server; they use the local clock.

Run the end-to-end tests, which call the real OpenRouter LLM and require `OPENROUTER_API_KEY`
and `LLM_JUDGE` to be set:

```bash
uv run pytest -m e2e
```

## Project structure

```
src/customer_support_fde/
├── cli.py                      # Entry point: --init-db, --set-tz, --graph, interactive mode
├── interactive.py              # Rich-based conversation loop, input limits, error handling
├── graph.py                    # LangGraph topology (nodes + edges)
├── state.py                    # Shared SupportState definition
├── messages.py                 # Customer-facing texts
├── circuit_breaker.py          # Primary/fallback LLM circuit breaker
├── pii.py                      # Presidio PII redaction of customer input
├── clock.py                    # Trusted current time from an NTP server
├── restaurant_time.py          # Restaurant timezone (from the database) and local-time display
├── db.py                       # SQLite schema, menu/order/refund/complaint/account persistence
├── refund_policy.py            # Refund eligibility rules
├── tickets.py                  # Ticket markdown rendering and file writing
├── tracing.py                  # Arize Phoenix/OpenTelemetry setup and log handler
├── menu/
│   └── menu.json                # Seed data for menu items
├── nodes/
│   ├── router_agent.py          # router_model: destination + sentiment
│   ├── clarify_intent.py        # clarify_intent_function
│   ├── account_identification_node.py
│   ├── order_support_agent.py   # order_agent / order_tools_function / order_await_customer_function
│   ├── refund_agent.py          # refund_agent / refund_tools_function / refund_await_customer_function
│   ├── cart_summary_node.py     # cart_summary_function
│   ├── ticket_gen_node.py       # ticket_gen_model
│   ├── memory_gen_node.py       # memory_gen_model
│   ├── tool_limit.py            # tool_limit_function
│   └── common.py                # build_llm, retries, history condensation, tool error handling
└── tools/
    ├── menu_tools.py
    ├── cart_tools.py
    └── refund_tools.py

docs/ARCHITECTURE.md             # Workflow diagram and per-node docs
specs/                           # Feature specs, plans and tasks
tests/
├── unit/                        # Unit tests per module/node
├── integration/                 # Multi-node trajectory tests
└── e2e/                         # Real-LLM end-to-end tests (marker: e2e)
```
