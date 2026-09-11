# Tool Contracts: Refund Policy Agent

This project has no HTTP/REST surface; the interface it exposes to an external caller (the LLM,
via LangChain tool-calling) is a set of `@tool`-decorated functions bound to an agent. This
document specifies the four tools this feature adds, following the shape established by
[`specs/006-cart-total-lookup/contracts/get_cart_total.md`](../../006-cart-total-lookup/contracts/get_cart_total.md).

**Module**: `src/customer_support_fde/tools/refund_tools.py`

**Registered on**: `refund_agent._REFUND_TOOLS` (`src/customer_support_fde/nodes/refund_agent.py`),
bound into the `refund_tools` `ToolNode` in `graph.py`.

**Shared conventions** (matching the existing cart and menu tools):

- Tools that mutate state return a `Command` carrying both the state update and a `ToolMessage`.
  Read-only tools may return a plain `str`.
- All customer-facing wording is **pre-rendered by the tool**, never left for the model to
  compose from structured data. This is the same reasoning that shaped `get_cart_total`: a
  rendered string leaves no decision for the model to re-derive, which is what makes FR-009 and
  SC-005 hold in practice.
- `state` arrives via `InjectedState` and is never a model-supplied argument.

---

## Tool: `lookup_order`

### Purpose

Retrieve a past order by the id the customer supplies, and make it the order under discussion
for the rest of the conversation (FR-001, FR-002).

### Input

| Parameter | Source | Type | Description |
|---|---|---|---|
| `order_id` | model | `str` | The order id as the customer stated it. Case, spacing, and dashes are normalized downstream; `O`/`I`/`L` are folded to `0`/`1`/`1` by the existing `db.normalize_order_id`. |
| `state` | `InjectedState` | `SupportState` | Injected. |
| `tool_call_id` | `InjectedToolCallId` | `str` | Injected. |

### Output

`Command` updating `order_lookup` and appending a `ToolMessage`.

- **Found**: `order_lookup` is set to the `db.get_order` result. The message renders the order's
  lines, quantities, unit prices, total, and placement time (FR-001).
- **Not found**: `order_lookup` is left unchanged and the message says the id matched no order
  and asks the customer to re-check it (FR-002). The tool never invents an order.

### Error handling

`MenuStoreError` (database missing) propagates — the existing CLI already renders it with the
`--init-db` remediation hint.

### Notes

Wraps the existing `db.get_order`, which already normalizes the id and returns `None` on a
miss. No new lookup logic is written.

---

## Tool: `process_refund_request`

The load-bearing tool. Evaluates the policy **and** writes the resulting record in one call, so
no code path reaches a stored refund request without passing the policy (research.md
Decision 2).

### Purpose

Apply the refund policy to the order under discussion and persist the outcome: a pending refund
request when eligible (FR-012), a complaint when denied (FR-018).

### Input

| Parameter | Source | Type | Description |
|---|---|---|---|
| `undelivered_items` | model | `list[UndeliveredItem]` | Ordered dishes the customer did not receive. `UndeliveredItem` is a Pydantic model: `{name: str, quantity: int}`, following the `CartRemoval` precedent in `cart_tools.py`. |
| `substitute_dishes` | model | `list[str]` | Names of dishes that arrived instead. **Empty** when nothing arrived — that emptiness is what triggers FR-006's waiver. Names only; never priced (FR-015). |
| `return_confirmed` | model | `bool` | Whether the customer explicitly agreed to bring the substitute back. Ignored when `substitute_dishes` is empty. |
| `customer_issue` | model | `str` | The customer's problem in their own terms. Becomes the complaint `description` if the refund is denied (FR-018). |
| `state` | `InjectedState` | `SupportState` | Injected. Supplies `order_lookup` — the order id is **not** a model argument (research.md Decision 3). |
| `tool_call_id` | `InjectedToolCallId` | `str` | Injected. |

### Preconditions

| Condition | Behavior |
|---|---|
| `state["order_lookup"]` is `None` | No evaluation, no write. Message tells the agent to look the order up first (FR-002). |
| A refund request already exists for the order | No second request. Message reports the existing request's status and amount (FR-011). |

### Output

`Command` appending a `ToolMessage` and updating state.

**Eligible** — updates `refund_request`:

- Writes one `refund_requests` row (`status = 'pending'`) plus its `refund_request_lines`.
- Amount is the sum of undelivered quantities at order-recorded unit prices (FR-014).
- Message states the amount, that the request is **submitted and awaiting review**, and — when
  a substitute was received — what the customer needs to bring back. It MUST NOT say the refund
  is complete (FR-016).

**Denied** — updates `complaint_ids`:

- Writes no refund request (FR-010).
- Writes or extends a complaint carrying `customer_issue` and the denial reason code (FR-018,
  FR-020, FR-021).
- Message names the specific policy condition that failed (FR-009, SC-005).

### Quantity handling

A reported quantity greater than the quantity actually ordered on that line is clamped to the
ordered quantity, and the message says so. A reported name matching no line on the order
contributes nothing and is reported back as unmatched. Together these keep SC-008 true
regardless of what the model reports.

### Error handling

A `sqlite3.Error` during the write surfaces as `OrderStoreError` and is rendered as an explicit
"your request could not be recorded" message (FR-025). The tool never reports a success it did
not achieve.

### Determinism

Eligibility comes entirely from `refund_policy.evaluate()`, which receives no sentiment
argument and no model-authored prose — only the order, the undelivered lines, the two booleans,
and an injected `now` (FR-027, SC-009).

---

## Tool: `log_complaint`

### Purpose

Record dissatisfaction where no refund was requested (US3, FR-017).

### Input

| Parameter | Source | Type | Description |
|---|---|---|---|
| `description` | model | `str` | The customer's issue in their own terms. |
| `state` | `InjectedState` | `SupportState` | Injected. Supplies `order_lookup` for the optional order link and `complaint_ids` for de-duplication. |
| `tool_call_id` | `InjectedToolCallId` | `str` | Injected. |

### Output

`Command` updating `complaint_ids` and appending a `ToolMessage` confirming the complaint was
recorded and passed to the restaurant.

- Links to `order_lookup`'s order when one has been retrieved; stores `order_id = NULL`
  otherwise (FR-019).
- `policy_reason` is `NULL` — this path is not a denial.
- If a complaint already exists for this (conversation, order) pairing, it is **extended**, not
  duplicated (FR-020), preserving `created_at` (FR-021).

### Error handling

Same as `process_refund_request`: a failed write yields an explicit "could not be recorded"
message rather than a false confirmation (FR-025).

---

## Tool: `conclude_refund_conversation`

### Purpose

Signal that the conversation has reached an outcome, terminating the refund loop and routing to
the ticket node. Mirrors `mark_order_confirmed` in `cart_tools.py`.

### Input

| Parameter | Source | Type | Description |
|---|---|---|---|
| `state` | `InjectedState` | `SupportState` | Injected. |
| `tool_call_id` | `InjectedToolCallId` | `str` | Injected. |

No model-supplied arguments.

### Output

`Command` setting `refund_resolved: True` and appending a short `ToolMessage`.

### Why this is a separate tool

Recording tools deliberately do not end the conversation. The spec's mixed-intent edge case
requires that a qualifying refund *and* an unrelated complaint both be recorded in one
conversation; if `process_refund_request` terminated the flow, the second record could never be
written (research.md Decision 8).

---

## Policy function contract (internal)

Not a tool — the LLM cannot reach it directly — but it is the contract every refund outcome
depends on.

**Module**: `src/customer_support_fde/refund_policy.py`

```python
REFUND_WINDOW_HOURS = 48

def evaluate(
    order: dict,                      # db.get_order shape
    undelivered: list[dict],          # [{name, quantity, unit_price, line_total}]
    substitute_received: bool,
    return_confirmed: bool,
    now: datetime,                    # injected; tests pin ages exactly
) -> PolicyDecision: ...
```

**Guarantees**:

1. Pure — no I/O, no model calls, no clock read. `now` is injected so tests can pin 47:59,
   exactly 48:00, and 48:01 without sleeping or freezing the clock.
2. No sentiment parameter exists, so sentiment cannot influence the outcome (FR-027, SC-009).
3. Eligible requires **all** of: within the window (FR-004), at least one undelivered line
   (FR-005), and either no substitute received or a confirmed return (FR-006, FR-007).
4. Every denial carries a `reason` code from the fixed set in
   [data-model.md](../data-model.md#policydecision-srccustomer_support_fderefund_policypy)
   (FR-009).
5. The 48-hour boundary is inclusive: eligible when `now - created_at <= 48h`.
