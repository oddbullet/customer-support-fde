# Feature Specification: Remove Items From Cart

**Feature Branch**: `003-remove-cart-items`

**Created**: 2026-09-10

**Status**: Draft

**Input**: User description: "Add another tool for the order_support_agent. Remove items from cart."

## Clarifications

### Session 2026-09-10

- Q: When a customer names an item to remove without specifying a count (e.g., "remove the fried rice"), should that take off the entire cart entry for that item, or just decrement its quantity by one? → A: Naming an item without a quantity removes the entire entry, regardless of its current quantity.
- Q: Should the removal tool also support taking off a specific partial quantity when the customer states a count, or should removing an item always take out the whole entry regardless of what's said? → A: Support partial quantity too — if the customer states a count, decrement by that amount instead of deleting the whole entry; unqualified requests still remove everything.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Remove an item the customer changed their mind about (Priority: P1)

A customer who has already added one or more items to their cart decides they no longer want one of them and asks the order/support agent to take it off their order.

**Why this priority**: This is the only capability in scope for this feature and it delivers the full value on its own — without it, a customer who changes their mind has no way to correct their cart short of starting over.

**Independent Test**: Can be fully tested by adding a known menu item to the cart, asking the agent to remove it, and confirming the item is no longer present in the conversation's cart contents.

**Acceptance Scenarios**:

1. **Given** a customer has one or more units of a menu item in their cart, **When** they ask the agent to remove that item without specifying a quantity, **Then** the item's cart entry is deleted entirely, regardless of how many units were present.
2. **Given** a customer has more than one unit of a menu item in their cart, **When** they ask the agent to remove a specific quantity of that item that is less than the amount in the cart, **Then** the item's cart entry remains with its quantity decremented by the requested amount.
3. **Given** a customer names a menu item using a partial name, minor typo, or close variation, **When** they ask the agent to remove it, **Then** the agent resolves it to the correct cart entry the same way item lookup and adding already do.
4. **Given** a customer asks to remove more than one distinct item in the same request, **When** the agent processes the request, **Then** each named item is removed (or decremented) independently and the customer is told the outcome for each.

---

### Edge Cases

- What happens when a customer asks to remove an item that exists on the menu but isn't currently in their cart? The agent tells the customer the item isn't in their cart rather than silently doing nothing or erroring.
- What happens when a customer asks to remove an item whose name has no reasonably close match on the menu at all? The agent reports it as not found, consistent with existing menu lookup behavior.
- What happens when a customer's item name ties between two or more menu items equally well? The agent lists the tied candidates and asks the customer which one they meant, consistent with existing add/lookup behavior.
- What happens when a customer asks to remove an item without stating a quantity? The agent removes the entire cart entry for that item, regardless of its current quantity.
- What happens when a customer asks to remove more units of an item than are currently in their cart? The agent removes all remaining units of that item (the entry is deleted) and tells the customer how many were actually removed, rather than erroring or leaving a negative quantity.
- What happens when a customer asks to remove an item after the cart has already been confirmed as finished? Out of scope for this feature — cart mutation after confirmation is not addressed here, matching how adding items is already handled.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The order/support agent MUST be able to remove a named menu item from the customer's in-progress cart, resolving partial names, minor typos, and close variations to the correct cart entry rather than requiring an exact name match.
- **FR-002**: When the customer asks to remove an item without specifying a quantity, the system MUST delete that item's entire cart entry, regardless of how many units were present.
- **FR-003**: When the customer specifies a quantity to remove that is less than the item's current cart quantity, the system MUST decrement that entry's quantity by the requested amount and keep the entry in the cart.
- **FR-004**: When a removal (whether unqualified or by quantity) reduces an item's quantity to zero, the system MUST delete that item's entry from the cart entirely rather than leaving a zero-quantity entry.
- **FR-005**: The system MUST tell the customer when they try to remove an item that is not currently in their cart, rather than silently doing nothing or erroring.
- **FR-006**: The system MUST tell the customer when the item name they used to request a removal has no reasonably close match on the menu, rather than silently failing or fabricating a response.
- **FR-006a**: When a customer's item name is tied between two or more menu items as equally close matches, the system MUST list the tied candidates and ask the customer to specify which one they meant, rather than auto-selecting one or reporting the item as not found.
- **FR-007**: When a customer specifies a quantity to remove that is greater than or equal to the item's current cart quantity, the system MUST remove all remaining units of that item (deleting the entry) and report the actual quantity removed, rather than erroring or producing a negative quantity.
- **FR-008**: The order/support agent MUST support removing more than one distinct item in a single request, with each named item (and its own optional quantity) resolved and removed independently of the others, and reported as not-in-cart / not-found / tied where applicable.

### Key Entities

- **Cart (menu_items)**: The existing per-conversation collection of distinct menu items and their quantities (see the order/support agent's cart feature). This feature only changes how entries are removed or decremented from it; it does not change how entries are added or structured.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A customer can remove a specific, existing cart item in a single request, with no follow-up needed.
- **SC-002**: 100% of cart removal requests for an item actually present in the cart result in that item's entry being accurately decremented or deleted, matching the requested removal (entire entry when no quantity is given, the specified amount otherwise).
- **SC-003**: Customers asking to remove an item not currently in their cart, or with no reasonably close menu match, receive a clear explanatory response instead of a silent no-op or fabricated confirmation, every time.
- **SC-004**: Customers whose removal request ties between two or more menu items are asked to pick among the tied candidates rather than receiving a guessed outcome.

## Assumptions

- The removal tool accepts one or more item names in a single call, each with an optional quantity; an item named without a quantity is removed entirely, while a quantity decrements that entry by the specified amount (capped at the entry's current quantity).
- Item-name resolution for removal reuses the same fuzzy-matching behavior (partial names, typos, tie handling, not-found handling) already defined for menu lookup and adding items, rather than introducing a separate matching strategy.
- Removing items is only meaningful while the cart is still open; behavior once the customer has confirmed they're finished ordering is out of scope, consistent with the existing add-to-cart tool not addressing that case either.
- No undo/history of removals is required — only the resulting cart state after a removal matters for this feature.
