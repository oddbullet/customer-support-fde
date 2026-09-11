# Feature Specification: Cart Summary at Order Confirmation

**Feature Branch**: `004-cart-summary-node`

**Created**: 2026-09-11

**Status**: Draft

**Input**: User description: "Once the customer is confirm their order. The confirm_node (change this to cart_summary node) will give the customer a summary of their order. Include the items and number of items they order. Give the total cost of their order."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Customer sees an itemized order summary with total (Priority: P1)

A customer finishes building their order and tells the support agent they are done. Before the
conversation closes out, the customer is shown a written recap of exactly what they ordered: each
dish by name, how many of each they are getting, and what the whole order costs. The customer can
read the recap and immediately tell whether it matches what they asked for.

**Why this priority**: This is the entire point of the feature. Without it, a customer confirms an
order and never learns what it contains or what they will pay — the highest-risk moment in the
ordering flow. Delivering only this story already gives customers a complete, verifiable record of
their order.

**Independent Test**: Run an ordering conversation that adds a few items, confirm the order, and
check that the resulting reply to the customer names every ordered item, states a quantity for
each, and states one order total. No other story needs to be built for this to be valuable.

**Acceptance Scenarios**:

1. **Given** a customer whose order contains 2 Kung Pao Chicken and 1 Hot and Sour Soup, **When**
   the customer confirms the order, **Then** the customer receives a summary listing "Kung Pao
   Chicken" with quantity 2 and "Hot and Sour Soup" with quantity 1, and a single order total equal
   to the sum of those items' prices at the stated quantities.
2. **Given** a customer whose order contains exactly one unit of one item, **When** the customer
   confirms the order, **Then** the summary lists that item with quantity 1 and an order total
   equal to that item's price.
3. **Given** a customer who added an item and later removed it so that only other items remain,
   **When** the customer confirms the order, **Then** the summary lists only the items still in the
   order and the total reflects only those items.
4. **Given** a confirmed order, **When** the summary is produced, **Then** the total shown is a
   currency amount rounded to two decimal places.

---

### User Story 2 - Support ticket matches what the customer was told (Priority: P2)

After the customer is shown the summary, a support ticket is produced for restaurant staff. The
ticket carries the same items, the same quantities, and the same total the customer saw, so staff
and customer are never working from different numbers when a question comes up later.

**Why this priority**: Valuable but secondary — the customer is already served by Story 1. This
story protects the downstream operational path and prevents disputes caused by a ticket that
disagrees with the customer's receipt.

**Independent Test**: Confirm an order, capture the summary shown to the customer, and compare the
generated ticket's items, quantities, and total against it; every value must agree.

**Acceptance Scenarios**:

1. **Given** a confirmed order for 3 units across 2 dishes, **When** the ticket is produced,
   **Then** the ticket's item list, per-item quantities, and total match the summary presented to
   the customer exactly.
2. **Given** a confirmed order, **When** the ticket is produced, **Then** the ticket records a
   per-item unit price and line total consistent with the order total.

---

### User Story 3 - Unpriceable or empty orders fail visibly, not silently (Priority: P3)

If an ordered item cannot be priced (for example, it is no longer on the menu), or the order turns
out to be empty at confirmation time, the customer is not shown a misleading total. They are told
plainly which item could not be priced, or that there is nothing to summarize.

**Why this priority**: A rare path, but a wrong total is worse than no total. This story keeps the
failure honest rather than producing a confidently incorrect receipt.

**Independent Test**: Confirm an order containing an item with no available price and verify the
summary flags that item rather than omitting it or treating it as free; separately, reach
confirmation with an empty order and verify the customer is told there is nothing to summarize.

**Acceptance Scenarios**:

1. **Given** a confirmed order containing an item that has no available price, **When** the summary
   is produced, **Then** the summary names that item as unpriced and does not present a total that
   silently excludes it.
2. **Given** confirmation is reached with no items in the order, **When** the summary is produced,
   **Then** the customer is told the order is empty and no total is presented.

---

### Edge Cases

- What happens when the same dish was added several times in separate turns? The summary MUST show
  one line for that dish with the combined quantity, not one line per add.
- What happens when an item's price has fractional cents after multiplication? Line totals and the
  order total MUST be rounded to two decimal places, and the displayed total MUST equal the sum of
  the displayed line totals.
- What happens when the order contains many distinct dishes? Every ordered dish MUST appear in the
  summary; none are truncated or grouped into an "and others" line.
- What happens when an item name resolves differently in the menu than the customer typed it? The
  summary MUST use the official menu name for the item, not the customer's phrasing.
- What happens when an item was removed down to zero units before confirmation? That item MUST NOT
  appear in the summary.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST present an order summary to the customer at the moment the order is
  confirmed, before the interaction concludes.
- **FR-002**: The summary MUST list every distinct item in the confirmed order, identified by its
  official menu name.
- **FR-003**: The summary MUST state the ordered quantity for each distinct item, with repeat
  additions of the same item consolidated into a single line carrying the combined quantity.
- **FR-004**: The summary MUST state the unit price and the line total (unit price × quantity) for
  each distinct item.
- **FR-005**: The summary MUST state a single order total equal to the sum of all line totals.
- **FR-006**: All monetary amounts in the summary MUST be presented as currency rounded to two
  decimal places, and the stated order total MUST equal the sum of the stated line totals.
- **FR-007**: Item prices used in the summary MUST come from the restaurant's menu, not from values
  supplied or implied by the customer.
- **FR-008**: When an item in the confirmed order cannot be priced from the menu, the summary MUST
  name that item as unpriced rather than omitting it or pricing it at zero.
- **FR-009**: When confirmation is reached with an empty order, the summary MUST tell the customer
  the order is empty and MUST NOT present an order total.
- **FR-010**: The support ticket produced after the summary MUST carry the same items, quantities,
  per-item prices, line totals, and order total that were presented to the customer.
- **FR-011**: The summary MUST be derived from the recorded contents of the confirmed order, so that
  the same confirmed order always yields the same summary values.

### Key Entities *(include if data involved)*

- **Confirmed Order**: The finalized set of items the customer committed to. Holds one entry per
  distinct menu item along with the number of units ordered.
- **Order Summary**: The customer-facing recap of a confirmed order. Contains one line per distinct
  item (menu name, quantity, unit price, line total) plus a single order total.
- **Support Ticket**: The staff-facing record produced after the summary. Carries the same item
  lines, quantities, prices, and order total as the Order Summary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of confirmed orders result in a summary that names every ordered item and states
  a quantity for each.
- **SC-002**: The order total shown to the customer matches an independent recalculation from menu
  prices and ordered quantities in 100% of confirmed orders.
- **SC-003**: A customer can read the summary and verify their order is correct without asking a
  follow-up question about what they ordered or what it costs.
- **SC-004**: The items, quantities, and total on the support ticket match the customer-facing
  summary in 100% of confirmed orders.
- **SC-005**: Confirmed orders containing an unpriceable item, or containing no items at all,
  produce an explicit message about that condition in 100% of cases, and never a total that
  silently omits the affected item.

## Assumptions

- The order total is the subtotal of menu item prices only. Tax, delivery fees, tips, discounts, and
  promotional codes are out of scope for this feature and are not added to or shown in the total.
- Prices are in a single currency (US dollars) as already recorded on the restaurant menu; currency
  conversion and multi-currency display are out of scope.
- The summary is a read-only recap presented after confirmation. Editing the order from the summary
  (adding, removing, or changing quantities at that point) is out of scope; a customer who wants
  changes is handled by the existing ordering conversation before confirming.
- The summary is presented in the same conversational channel the customer has been using to order;
  no email, SMS, or printed receipt is produced by this feature.
- Per the feature request, the existing order-confirmation step in the support flow is renamed to a
  cart summary step, and this feature's behavior lives there. Downstream ticket generation continues
  to run after it.
- Menu item names and prices are available at confirmation time from the existing restaurant menu
  already used during the ordering conversation.
- Refund-related flows are unaffected; this feature applies only to the ordering path.
