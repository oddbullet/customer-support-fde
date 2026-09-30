# Customer Support FDE

An agentic customer support system for a Chinese restaurant. It answers menu and
ingredient/allergy questions, takes orders, and handles post-order complaints and refund
requests, producing a support ticket for every resolved conversation.

## Overview

The assistant runs as a LangGraph state machine driven by an LLM (via OpenRouter). A router
agent classifies each incoming message and hands it off to the order/support flow or the
refund flow; each flow uses tool-calling to look up the menu, place orders, or process refunds
against restaurant policy. Conversations are interactive (CLI, `rich`-rendered) and every
resolved conversation ends with a generated ticket and, for identified accounts, an updated
preferences memory.

## Architecture

```
                      ┌───────────────┐
                      │ router_agent  │  classifies destination + sentiment
                      └───────┬───────┘
                clarify ◄─────┼─────► order_support / refund
                (unclear)     │
                              ▼
          ┌────────────────────────────────────┐
          │ account_identification_node         │  order/support path
          └──────────────────┬───────────────────┘
                              ▼
                     call_model ⇄ order_tools   (menu lookup, cart, ordering)
                              │
                              ▼
                       await_customer ⇄ call_model  (confirm order)
                              │
                              ▼
                  cart_summary ──► ticket_gen_node   (order ticket)
                        │
                        └────────► memory_gen_node   (update account preferences)

                     refund_agent ⇄ refund_tools     (refund path)
                              │
                              ▼
                  refund_await_customer ⇄ refund_agent
                              │
                              ▼
                       ticket_gen_node               (refund ticket)
```

- **Router Agent** — entry point for every message. Classifies the request as
  `order_support`, `refund`, or `unclear`, and separately assesses sentiment (surfaced only to
  the refund agent).
- **Order/Support Agent** — answers menu and ingredient/allergy questions and manages ordering
  through tool calls, backed by the SQLite menu table.
- **Refund Agent** — handles post-order complaints and refund requests against restaurant
  policy (`refund_policy.py`), recording refund requests and complaints in SQLite.
- **Ticket Summary Agent** (`ticket_gen_node`) — produces the final ticket artifact (order
  ticket or refund ticket) written to the `tickets/` directory.
- **Account Identification / Memory Gen nodes** — identify or create a customer account and
  persist a free-text preferences summary (likes, dislikes, allergies) after each order.

Tracing is instrumented with Arize Phoenix (OpenTelemetry) when a collector endpoint is
configured.

## Prerequisites

- Python 3.14 (see `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) for dependency management and running the project
- An [OpenRouter](https://openrouter.ai/) API key
- Internet access (for LLM calls, and for `--graph` which renders via the Mermaid.ink API)

## Installation

```bash
git clone https://github.com/oddbullet/customer-support-fde
cd customer-support-fde
uv sync
```

`uv sync` creates a virtual environment and installs all dependencies from `pyproject.toml` /
`uv.lock`.

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | API key used to call the LLM through OpenRouter. |
| `OPENROUTER_MODEL` | Yes | OpenRouter model id (e.g. `deepseek/deepseek-v4-flash-0731`). |
| `LLM_JUDGE` | For e2e tests | Model id used as an LLM judge in end-to-end tests. |
| `PHOENIX_COLLECTOR_ENDPOINT` | No | Enables Arize Phoenix tracing when set. |
| `CUSTOMER_SUPPORT_DB` | No | Path to the SQLite database file. Defaults to `customer_support.db`. |
| `CUSTOMER_SUPPORT_TICKETS_DIR` | No | Directory tickets are written to. Defaults to `tickets/`. |

## Running the application

The menu and confirmed orders live in a SQLite database, not `menu/menu.json` (which now only
serves as seed data). Before running any conversation, initialize and seed the database:

```bash
uv run start --init-db
```

This is idempotent and safe to re-run after editing `menu.json` — it updates existing dishes
and inserts new ones without deleting anything.

Set the restaurant's timezone once (stored in the database; one of `eastern`, `central`,
`mountain`, `arizona`, `pacific`, `alaska`, `hawaii`). Every time shown to customers and the
agent is converted to it; storage and the refund window stay in UTC:

```bash
uv run start --set-tz eastern
```

Order and refund times come from an NTP server (`time.windows.com`), not the computer's clock, so
the app needs internet access to it (UDP port 123).

Then start an interactive conversation:

```bash
uv run start
```

Type a question, an order, or a refund request; `/exit` or Ctrl+C quits.

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

Run the end-to-end tests, which call the real OpenRouter LLM and require `OPENROUTER_API_KEY`
and `LLM_JUDGE` to be set:

```bash
uv run pytest -m e2e
```

## Project structure

```
src/customer_support_fde/
├── cli.py                      # Entry point: --init-db, --set-tz, --graph, interactive mode
├── clock.py                    # Trusted current time from an NTP server
├── restaurant_time.py          # Restaurant timezone (from the database) and local-time display
├── interactive.py              # Rich-based interactive conversation loop
├── pii.py                      # Presidio PII redaction of customer input
├── graph.py                    # LangGraph topology (nodes + edges)
├── state.py                    # Shared SupportState definition
├── db.py                       # SQLite schema, menu/order/refund/account persistence
├── tickets.py                  # Ticket markdown rendering and file writing
├── tracing.py                  # Arize Phoenix/OpenTelemetry setup
├── refund_policy.py            # Refund eligibility rules
├── menu/
│   └── menu.json                # Seed data for menu items
├── nodes/
│   ├── router_agent.py          # Destination + sentiment classification
│   ├── clarify_intent.py        # Handles "unclear" routing
│   ├── account_identification_node.py
│   ├── order_support_agent.py   # call_model / order_tools / await_customer
│   ├── refund_agent.py          # refund_agent / refund_tools / refund_await_customer
│   ├── cart_summary_node.py
│   ├── ticket_gen_node.py
│   ├── memory_gen_node.py       # Updates account preferences after an order
│   └── common.py
└── tools/
    ├── menu_tools.py
    ├── cart_tools.py
    └── refund_tools.py

tests/
├── unit/                        # Unit tests per module/node
├── integration/                 # Multi-node trajectory tests
└── e2e/                         # Real-LLM end-to-end tests (marker: e2e)
```
