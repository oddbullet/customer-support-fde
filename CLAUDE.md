# Project Overview
An agentic customer support system for a Chinese restaurant that assists customers with menu questions, ingredient and allergy inquiries, order placement, and refund requests.

This project is still in development. A .env fil is set with an Openrouter API key using deepseek/deepseek-v4-flash-0731.

# Plan Architecture
- Router Agent:
    - Purpose: Entry point for all customer interactions.
    - This agent will route the user request to the correct specialized agent to assist them. Additionally, it should give a sentiment analysist that will only be given to the refund agent. 

- Order Agent:
    - Purpose: Handles general customer support and ordering.
    - This agent will help the customer with ordering and answering any questions related to the menu.

- Refund Agent:
    - Purpose: Handles customer complaints and refunds request as according to restaurant policy.
    - The idea for this agent is to handle customer interaction post orders. 

- Ticket Summary Agent:
    - Purpose: Produces the final support ticket summary artifact.
    - Two types of tickets: refund ticket and order / support ticket.

# Tech Stack
- LangGraph
- Arize Phoenix
- PyTest
- Python
- SQLite
- Rich

# Development

Write or modified the test first before writing the actual code. Use Test Driven Development.

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