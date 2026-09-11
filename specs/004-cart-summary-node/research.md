# Phase 0 Research: Cart Summary at Order Confirmation

The spec carries no `NEEDS CLARIFICATION` markers — the open questions in the request (tax, currency,
editability, delivery channel) were closed with documented defaults in the spec's Assumptions
section. What remains are five technical decisions about how the summary is computed, where its
numbers live, and how they reach the customer.

## 1. Who composes the summary: deterministic Python vs. the order-support LLM

**Decision**: `cart_summary_node` computes and renders the summary itself, in plain Python. No LLM
call is made at or after confirmation.

**Rationale**: FR-005/FR-006 require the stated total to equal the sum of the stated line totals, and
SC-002 requires that total to survive an independent recalculation in 100% of orders. Arithmetic is
the one thing a language model cannot be relied on to get right every time, and verifying it would
require live-model tests — which this project has deliberately avoided (see
`specs/002-order-support-agent/research.md` §9, where reply-quality checks were pushed to a manual
checklist precisely because they can't be asserted offline). A pure function over
`dict[str, int]` plus menu prices is exactly testable with no API key, satisfies FR-011's
determinism requirement by construction, and adds no new LLM call site to trace or pay for.

**Alternatives considered**: Prompting the existing `call_model` to produce a closing recap —
rejected: it moves a hard numeric guarantee into the least reliable and least testable part of the
system. Having the LLM narrate a *pre-computed* summary handed to it as context — rejected under
Principle III (YAGNI): it adds a model round-trip and a paraphrase-drift risk to buy conversational
polish the spec never asks for.

## 2. Where the numbers live: a new `order_summary` state field vs. recomputing in `ticket_gen_node`

**Decision**: `cart_summary_node` writes a structured `order_summary` dict onto `SupportState`, and
`ticket_gen_node` builds `order_ticket` from it rather than from `menu_items`.

**Rationale**: FR-010 and SC-004 require the ticket to carry the same items, quantities, unit prices,
line totals, and total the customer saw. Two independent computations over the same inputs can
disagree the moment either one changes — that divergence is the specific failure SC-004 exists to
catch. Passing one computed structure downstream makes the guarantee structural instead of
coincidental, and is less code than a second pricing pass. This is the feature's only new
`SupportState` field.

**Alternatives considered**: Recompute prices inside `ticket_gen_node` from `menu_items` — rejected
for the drift reason above, and because it would read menu prices a second time at a later moment,
reintroducing a window where the two readings differ. Merge `ticket_gen_node` into
`cart_summary_node` to avoid passing anything — rejected: the two nodes serve different audiences
(customer vs. staff) and the spec's Assumptions explicitly keep ticket generation running after the
summary step.

## 3. Money arithmetic: `decimal.Decimal` vs. raw floats vs. integer cents

**Decision**: Compute with stdlib `decimal.Decimal`, built from `Decimal(str(price))`. Each line
total is `unit_price * quantity` quantized to `0.01` with `ROUND_HALF_UP`; the order total is the sum
of the already-quantized line totals. Amounts are stored in `order_summary`/`order_ticket` as
`float` rounded to two decimals (JSON-serializable for the CLI's `--json` mode) and rendered as
`$%.2f`.

**Rationale**: FR-006 requires the displayed total to equal the sum of the displayed line totals.
Rounding each line first and then summing is the only ordering that guarantees this; rounding a sum
of unrounded products can land a cent away from what the customer can add up on screen. `Decimal`
makes that rounding exact and explicit, and it is stdlib — no new dependency, so Principle III is
untouched. Prices come out of `menu.json` as JSON floats, hence `Decimal(str(price))` rather than
`Decimal(price)`, which would carry the float's binary error into the decimal.

**Alternatives considered**: Plain floats with `round(x, 2)` — workable for this menu's price range
but leaves binary representation error in the arithmetic for no saving, and makes the rounding order
easy to get silently wrong later. Integer cents throughout — rejected under YAGNI: it would require
converting the menu's float prices at every boundary and reads worse for a cart of a few items.
Storing `Decimal` in state — rejected: not JSON-serializable, which would break the CLI's `--json`
path the moment the summary is included there.

## 4. Price lookup: exact canonical-name match vs. reusing `resolve_menu_item`'s fuzzy matcher

**Decision**: A new `price_for_item(name: str, menu: list[MenuItem]) -> float | None` in
`tools/menu_tools.py` that matches the menu's `name` field exactly and returns `None` when nothing
matches.

**Rationale**: `menu_items` keys are already canonical — `add_items_to_cart` stores
`match.item["name"]`, never the customer's phrasing — so fuzzy matching at summary time would be
re-solving a problem already solved upstream, and worse, could quietly price an item as some *other*
menu item if the menu changed underneath. An exact miss is the honest signal that the item is no
longer priceable, which is precisely the FR-008 condition. Returning `None` rather than raising lets
the node report the item as unpriced instead of failing the whole summary.

**Alternatives considered**: Reuse `resolve_menu_item` — rejected for the mispricing risk above; its
`tie`/`not_found` statuses also have no meaningful interpretation when the input is already a
canonical name. Store the unit price in the cart at add time (making `menu_items` a richer
structure) — rejected: it changes `menu_items`' shape, which 002 and 003 both depend on, and would
freeze a price at add time, a pricing-policy decision the spec never asked for.

## 5. How the summary reaches the customer

**Decision**: `cart_summary_node` appends the rendered text as an `AIMessage` on `messages`, and
`cli.py` prints it. `_print_result` gains a branch that prints the summary text when the order was
confirmed; `--json` gains the structured `order_summary` alongside the existing payload. The
initial-state dict in `cli.py` gains `"order_summary": None`.

**Rationale**: FR-001 requires the summary to be *presented to the customer*, and the CLI is the
customer-facing channel. Today `_print_result` prints only `destination` and `query`, so a summary
written to state alone would never be seen — the feature would be untestable end-to-end and
unobservable to the person it is for. Putting the text on `messages` keeps the customer-facing
channel consistent with every other node in the graph; note that `await_customer` stops clearing
`messages` once `order_confirmed` is set (it returns early), so the appended `AIMessage` survives
to `END`.

**Alternatives considered**: Store the rendered text in a second state field — rejected: `messages`
already exists for exactly this and a second field would need its own reducer reasoning. Print from
inside the node — rejected under Principle IV, which puts agent output through traced state rather
than raw stdout, and Principle II, which keeps the library free of console coupling.

## 6. Reachability of the empty-cart branch (FR-009)

**Note, not a decision**: `mark_order_confirmed` already refuses to set `order_confirmed` on an empty
cart, so on today's graph `cart_summary_node` cannot be reached with an empty `menu_items` — the
integration test `test_confirming_with_an_empty_cart_never_reaches_confirm_node` asserts exactly
that. FR-009 is therefore implemented and unit-tested as a defensive branch on the pure function, not
as a live conversational path. This is worth stating plainly so the branch isn't later mistaken for
dead code and deleted: it is the guard that keeps a future graph change from producing a `$0.00`
receipt.

## Outcome

No `NEEDS CLARIFICATION` markers remain. No new third-party dependency (`decimal` is stdlib), no new
graph node, no new tool. One new `SupportState` field (`order_summary`), one module rename, and one
backward-incompatible `order_ticket` shape change — all disclosed in
[plan.md](./plan.md)'s Constitution Check under Principle IV.
