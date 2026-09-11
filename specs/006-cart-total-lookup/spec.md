# Feature Specification: Cart Total Lookup

**Feature Branch**: `006-cart-total-lookup`

**Created**: 2026-09-11

**Status**: Draft

**Input**: User description: "For the order_support_agent, I don't want it to do math when the customer ask for the total. Give it a tool that will give the total fo the current items in the cart."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Customer asks for the running total mid-order (Priority: P1)

While building their order, a customer asks the order support agent how much their cart currently costs. The agent looks up the exact total rather than calculating or estimating it, and reports that figure back to the customer.

**Why this priority**: This is the core problem being fixed — customers must be able to trust the total they're told, and today the agent may compute it itself, risking an incorrect answer.

**Independent Test**: Add a known set of items with known prices to a cart, ask "what's my total?", and verify the reported total exactly matches the sum of the item prices.

**Acceptance Scenarios**:

1. **Given** a cart containing one or more priced items, **When** the customer asks for the total, **Then** the agent reports a total that exactly matches the sum of each item's price times its quantity.
2. **Given** a cart containing multiple different items with varying quantities, **When** the customer asks for the total, **Then** the reported total accounts for every item and quantity currently in the cart.

---

### User Story 2 - Customer updates the cart, then asks for the total again (Priority: P2)

A customer adds or removes items partway through the conversation, then asks for the total. The reported total reflects the cart's current contents, not a stale or earlier total.

**Why this priority**: Ensures the total stays trustworthy across the whole conversation, not just on the first request.

**Independent Test**: Add items, ask for the total, then remove or add an item and ask again — verify the second total reflects only the updated cart contents.

**Acceptance Scenarios**:

1. **Given** a customer has already asked for and received a total, **When** they add another item and ask again, **Then** the new total includes the added item.
2. **Given** a customer has already asked for and received a total, **When** they remove an item and ask again, **Then** the new total excludes the removed item (or reflects the reduced quantity).

---

### User Story 3 - Customer asks for the total with an empty cart (Priority: P3)

A customer asks for the total before adding anything to their cart. The agent tells them the cart is empty instead of stating a numeric total.

**Why this priority**: A lower-frequency edge case, but answering "$0.00" or guessing would be confusing and inconsistent with how an empty cart is handled elsewhere in the system.

**Independent Test**: With no items in the cart, ask "what's my total?" and verify the response clearly states there's nothing in the cart yet, with no numeric total given.

**Acceptance Scenarios**:

1. **Given** an empty cart, **When** the customer asks for the total, **Then** the agent responds that the cart is empty rather than returning a dollar amount.

---

### Edge Cases

- What happens when the customer asks for the total immediately after an item is added or removed in the same turn? The total must reflect the cart state as of that point in the conversation, not a prior snapshot.
- How does the system handle a cart total whose exact cents value doesn't round evenly (e.g. fractional-cent line items)? The total must be rounded using the same rule already used when the order is finalized, so the quoted total never falls short of the amount the customer is ultimately charged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The order support agent MUST determine the customer's cart total by invoking a dedicated total-lookup capability rather than computing or estimating the figure itself.
- **FR-002**: The total-lookup capability MUST calculate the total from the cart's current contents (item names and quantities) and each item's current menu price at the moment of the request.
- **FR-003**: The total-lookup capability MUST account for every item and its full quantity currently in the cart — no item or unit may be omitted from the calculation.
- **FR-004**: The total-lookup capability MUST round the total using the same rounding rule used when an order is finalized, so a total quoted mid-conversation never understates what the customer will actually owe.
- **FR-005**: When the cart is empty, the total-lookup capability MUST indicate that the cart is empty rather than returning a numeric total.
- **FR-006**: The agent MUST relay the total returned by the capability to the customer without altering, re-deriving, or approximating the value.
- **FR-007**: A total requested immediately after the cart changes (items added or removed) MUST reflect the updated cart contents.

### Key Entities

- **Cart**: The set of menu items and quantities the customer has currently chosen to order, prior to order confirmation.
- **Menu Item**: A dish available for order, with a current price used to value cart contents.
- **Cart Total**: The monetary sum owed for all items currently in the cart, derived from menu prices and cart quantities.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of cart total responses exactly match the sum of current cart item prices times quantities — zero arithmetic discrepancies.
- **SC-002**: Customers receive the cart total in the same reply in which they asked for it, with no perceptible added delay.
- **SC-003**: A total quoted during the conversation matches the total on the final order confirmation in 100% of cases where the cart was not changed in between.
- **SC-004**: Customers asking for a total on an empty cart receive a clear "cart is empty" response instead of a numeric or confusing answer in 100% of cases.

## Assumptions

- The order support agent already has access to the customer's current cart contents and the live menu, so no new data source is required — only a new way of deriving the total from data the agent can already see.
- The rounding behavior for the cart total should match the rounding already used elsewhere in the system when an order is finalized, so quoted totals stay consistent with actual charges (round up to the nearest cent).
- The total-lookup capability returns the overall cart total; it is not required to also enumerate a full line-item breakdown, since the customer's request in scope is specifically for "the total."
- Menu prices referenced by the total are the prices in effect at the time of the request.
