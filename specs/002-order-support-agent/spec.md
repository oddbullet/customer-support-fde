# Feature Specification: Order/Support Agent with Menu Tools

**Feature Branch**: `002-order-support-agent`

**Created**: 2026-09-09

**Status**: Draft

**Input**: User description: "Move all the agents code into a new folder, call nodes for organization. Create a tool folder where all tools will live. Create the order/support agent. This agent will help the customer with ordering and answering any questions related to the menu. It will have the tools: get_menu_item() this tool will get an item from the menu and return the full detail. get_menu() will return everything on the menu. add_item_to_cart() will add a menu item to cart. The graph state should include another state. menu_items. This state will be use for a future agent to create a order ticket. Create a dummy ticket generate agent and connect it to the order agent. A menu item is define as name, price, ingredients. Finally, creat a new folder call menu. In here will live a JSON, of the menu. Create 5 menu items."

## Clarifications

### Session 2026-09-09

- Q: Should the order-ticket-generation step run every time the order/support agent finishes responding, or only when the customer has actually added at least one item to their order, and how is "finished ordering" detected? → A: The order-ticket step only runs once the customer is finished ordering. Items are accumulated into an array as they're added. "Finished" is detected via an explicit confirmation step: after each item is added, the agent asks whether the customer wants anything else, and only proceeds to ticket generation once the customer explicitly confirms they're done.
- Q: When a customer refers to a menu item by name, how exact does the match need to be for the system to recognize it as that item? → A: Flexible/fuzzy match — the system accepts partial names, minor typos, or close variations and resolves them to the closest matching menu item using best-effort matching, rather than requiring an exact (even if case-insensitive) name match.
- Q: Should the in-progress collection of items a customer has added be called "cart" or "order" throughout the spec? → A: Cart — matches the originally requested tool name (add_item_to_cart). "Cart" is the in-progress collection the customer builds up during the conversation; once the customer confirms they're finished, the cart's contents become their finalized order, which is what the order ticket is built from.
- Q: When a customer adds the same menu item to their cart more than once, should each addition be a separate cart entry, or should the cart track a quantity/count field per distinct item? → A: Quantity field per distinct item — the cart holds one entry per distinct menu item with a quantity that increments on repeat adds of the same item, rather than a flat list with duplicate entries.

### Session 2026-09-10

- The hand-off from the order/support agent to the order-ticket-generation step is now routed through a dedicated intermediate confirmation step (`confirm_node`), rather than the order/support agent invoking ticket generation directly. The order/support agent connects to `confirm_node`, and `confirm_node` connects to the ticket-generation step. Both remain placeholder/dummy steps for this phase (see Assumptions).
- Q: When a customer's item name matches two or more menu items equally well (a tie in the fuzzy match), how should the agent respond? → A: Ask the customer to pick — the agent lists the tied candidates and asks the customer which one they meant, rather than guessing or reporting "not found."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask about the menu and specific items (Priority: P1)

A customer chatting with support wants to know what dishes are available and what's in a specific dish before deciding whether to order it.

**Why this priority**: Answering menu and ingredient questions is the core, most frequent reason a customer reaches the order/support agent, and it has no dependency on any other capability.

**Independent Test**: Can be fully tested by asking "What's on the menu?" and "What's in [dish name]?" in a conversation and confirming the agent returns the complete menu list, and the full name/price/ingredients detail for the named dish, respectively.

**Acceptance Scenarios**:

1. **Given** a customer is talking to the order/support agent, **When** they ask what's available, **Then** the agent returns every item currently on the menu.
2. **Given** a customer names a specific dish that exists on the menu, **When** they ask for details, **Then** the agent returns that item's name, price, and ingredients.
3. **Given** a customer names a dish that has no reasonably close match on the menu, **When** they ask for details, **Then** the agent tells them the item was not found instead of guessing or fabricating details.
4. **Given** a customer names a dish using a partial name, minor typo, or close variation of an existing menu item's name, **When** they ask for details, **Then** the agent resolves it to that menu item and returns its details.
5. **Given** a customer names a dish whose closest matches are two or more menu items tied for best match, **When** they ask for details or to add it to their cart, **Then** the agent lists the tied candidates and asks the customer which one they meant, instead of guessing or reporting the item as not found.

---

### User Story 2 - Add menu items to a cart (Priority: P2)

A customer who has decided what they want tells the agent to add specific dishes to their cart.

**Why this priority**: Building the cart is the natural next step after browsing the menu, and it produces the data the ticket needs — but it depends on menu lookup (Story 1) being in place first.

**Independent Test**: Can be fully tested by asking the agent to add a known menu item to the cart and confirming the item appears in the conversation's running cart contents.

**Acceptance Scenarios**:

1. **Given** a customer has identified a menu item they want, **When** they ask the agent to add it to their cart, **Then** the item is recorded against that conversation's cart.
2. **Given** a customer asks to add an item that isn't on the menu, **When** the agent processes the request, **Then** the agent declines and explains the item isn't available, and nothing is added to the cart.
3. **Given** a customer adds more than one distinct item over the course of the conversation, **When** the cart is later reviewed, **Then** all previously added items are still present alongside the new one.
4. **Given** a customer adds the same menu item to their cart more than once, **When** the cart is later reviewed, **Then** that item appears as a single entry whose quantity reflects the number of times it was added.

---

### User Story 3 - Produce an order ticket from the conversation (Priority: P3)

Once a customer has finished building their cart through the order/support agent, the system prepares an order ticket capturing what was ordered.

**Why this priority**: Ticket creation is the payoff of the ordering flow but is only meaningful after items have actually been added to a cart (Story 2), so it's the last piece needed for an end-to-end path.

**Independent Test**: Can be fully tested by completing an ordering conversation that adds at least one item, then confirming a ticket artifact is produced that reflects the ordered items.

**Acceptance Scenarios**:

1. **Given** a customer has added one or more items to their cart, **When** the agent asks if they want anything else and the customer confirms they're done, **Then** the flow passes through a dedicated confirmation step, which then hands off to the order-ticket-generation step so a ticket is generated referencing the items that were added.
2. **Given** a customer has added an item, **When** the agent asks if they want anything else and the customer adds another item instead of confirming they're done, **Then** the confirmation step is not reached, the ticket step does not run, and the agent asks again after the new item is recorded.
3. **Given** a customer's conversation ends without ever adding an item, **When** the conversation ends, **Then** neither the confirmation step nor the ticket step ever runs (there is nothing to confirm or generate a ticket for).

---

### Edge Cases

- What happens when a customer asks about the menu before any items exist? (Not applicable here — the menu is always seeded with content — but the agent must still handle an empty result gracefully if it ever occurs.)
- What happens when a customer asks for an item using a name that doesn't exactly match any menu entry (typo, partial name, different casing)? The agent should resolve it to the closest matching menu item via flexible matching; only when no reasonably close match exists should it report the item wasn't found.
- What happens when a customer's item name is tied between two or more menu items equally well? The agent should list the tied candidates and ask the customer to pick one, rather than guessing which one they meant or reporting the item as not found.
- What happens when a customer tries to add the same item to their cart more than once? The item's quantity on its existing cart entry should increment rather than creating a duplicate entry.
- What happens when a customer asks a question unrelated to the menu or ordering while talking to this agent? Out of scope for this feature — routing to the correct agent is handled upstream.
- What happens when a customer says they're done without having added any items? The agent should acknowledge this rather than proceeding to ticket generation, since there is nothing to put on a ticket.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The order/support agent MUST be able to return the full detail (name, price, ingredients) for a single menu item the customer names, resolving partial names, minor typos, and close variations to the correct menu item rather than requiring an exact name match.
- **FR-002**: The order/support agent MUST be able to return the complete menu when a customer asks what's available.
- **FR-003**: The order/support agent MUST be able to add a named menu item to the customer's in-progress cart.
- **FR-004**: The system MUST retain the distinct items a customer has added to their cart, each with a quantity that increments when the customer adds that same item again, for the duration of the conversation, so a later step can use it to build an order ticket.
- **FR-005**: The system MUST tell the customer when they ask about or try to add an item that has no reasonably close match on the menu, rather than silently failing or fabricating a response.
- **FR-005a**: When a customer's item name is tied between two or more menu items as equally close matches, the system MUST list the tied candidates and ask the customer to specify which one they meant, rather than auto-selecting one or reporting the item as not found.
- **FR-006**: After each item is added to the cart, the order/support agent MUST ask the customer whether they'd like to add anything else, and MUST treat the cart as finalized only once the customer explicitly confirms they have nothing more to add.
- **FR-007**: The conversation flow MUST proceed to a dedicated confirmation step only after the customer has added at least one item to their cart and explicitly confirmed they are finished ordering (per FR-006); it MUST NOT proceed to that step otherwise.
- **FR-008**: The confirmation step MUST be the one that hands the finalized cart off to the order-ticket-generation step; the order/support agent MUST NOT invoke ticket generation directly. The order-ticket-generation step MUST produce a ticket artifact that reflects the items accumulated during the conversation; for this phase, both the confirmation step and the ticket-generation step are acceptable as placeholder/dummy implementations, standing in for the full confirmation and ticket summary capabilities described elsewhere in the project's architecture.
- **FR-009**: The restaurant's menu MUST contain at least 5 items, each defined by a name, a price, and a list of ingredients.
- **FR-010**: Agent logic (existing and new) MUST live under a single, dedicated area of the codebase reserved for agent nodes, separate from other code.
- **FR-011**: Tool implementations used by agents (including the menu-lookup and cart tools introduced here) MUST live under a single, dedicated area of the codebase reserved for tools, separate from agent logic.
- **FR-012**: The menu content MUST be stored as structured data in a dedicated, self-contained location separate from agent and tool code, so it can be updated independently.

### Key Entities

- **Menu Item**: A single dish the restaurant offers. Defined by name, price, and ingredients (a list).
- **Menu**: The full collection of menu items available to be browsed or queried.
- **Cart (menu_items)**: The collection of distinct menu items a customer has added during a single conversation, each with a quantity that increments on repeat adds of the same item; once the customer confirms they're finished, the cart's contents become the finalized order that a later step uses to build an order ticket.
- **Order Ticket**: The artifact produced at the end of an ordering conversation, referencing the items in the customer's finalized cart (their order). Full formatting/content is owned by the project's ticket summary capability; this feature only guarantees a ticket step is reached with that order data available to it.
- **Confirmation Step (`confirm_node`)**: A dedicated step between the order/support agent and the order-ticket-generation step. It is reached only once the customer has confirmed they're finished ordering, and it is responsible for handing the finalized cart off to ticket generation. A placeholder/dummy implementation for this phase.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A customer can get the full details of any specific, existing menu item in a single request, with no follow-up needed.
- **SC-002**: A customer can see the entire menu in a single request.
- **SC-003**: 100% of successfully added cart items are present when the order-ticket step runs for that conversation.
- **SC-004**: Every order/support conversation where the customer adds at least one item and explicitly confirms they're finished reaches the order-ticket step, and no conversation reaches that step before such confirmation.
- **SC-005**: Customers asking about a menu item with no reasonably close match receive a clear "not found" response instead of an incorrect or fabricated answer, every time; customers using a slightly misspelled or partial but recognizable item name still get the correct item; customers whose phrasing ties between two or more items are asked to pick among the tied candidates rather than receiving a guessed or fabricated answer.

## Assumptions

- The menu is fixed, seeded content (5 items) for this phase rather than data sourced from a live database or external system.
- The "dummy" order-ticket-generation step is an intentional placeholder: it only needs to run and have access to the cart's items, not produce the final, fully-formatted ticket (that remains the responsibility of the project's ticket summary agent per the overall architecture).
- The confirmation step (`confirm_node`) that sits between the order/support agent and the order-ticket-generation step is likewise an intentional placeholder for this phase: it only needs to exist as a distinct step that receives control once the customer confirms they're done and passes the finalized cart on to ticket generation, not implement additional confirmation logic beyond what FR-006 already describes.
- A customer's cart (menu_items) is scoped to a single conversation session and is not persisted beyond it in this feature.
- No payment processing, order confirmation messaging, or inventory/stock checks are part of this feature.
- Reorganizing existing agent code into a dedicated agent-nodes area does not change the existing router agent's or refund agent's external behavior.
