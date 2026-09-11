# Feature Specification: SQLite Menu and Order Records

**Feature Branch**: `json-to-sqlite`

**Created**: 2026-09-11

**Status**: Draft

**Input**: User description: "Migrate the JSON menu to SQLite. The database should be load once during the start of the graph run. THe tool will no longer pull in the JSON but instead for SQLite. For the cart_summary_node. Add the complete order to the database. The node output should now include an order id."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Menu answers come from the menu database (Priority: P1)

A customer asks what's on the menu, what a dish costs, or what's in a dish. The support agent
answers from the restaurant's menu database rather than from a menu file bundled inside the
application. Restaurant staff can correct a price, fix an ingredient list, or add a dish in that
database and have the next conversation reflect the change — without anyone shipping a new build of
the support system.

**Why this priority**: Every menu question, every item added to a cart, and every price on a summary
depends on this data. Moving it to the database is the point of the feature, and once this story is
done the system already delivers its core value: menu data that staff own and can change.

**Independent Test**: Point the system at a menu database, ask the agent for the full menu and for
one dish by name, and confirm the replies list exactly the dishes, prices, and ingredients held in
that database. Then change a price in the database, start a new conversation, and confirm the new
price is quoted. No other story needs to be built for this to be valuable.

**Acceptance Scenarios**:

1. **Given** a menu database holding six dishes, **When** a customer asks for the full menu, **Then**
   the reply lists all six dishes with the name, price, and ingredients recorded in the database, and
   no dish that is absent from it.
2. **Given** a menu database in which one dish's price has been changed since the last conversation,
   **When** a new conversation starts and the customer asks that dish's price, **Then** the updated
   price is quoted.
3. **Given** a customer who names a dish inexactly (for example "kung pao"), **When** the agent looks
   it up, **Then** the matching behavior customers see today is preserved — a single confident match
   is answered directly, an ambiguous name prompts the customer to choose between the candidates, and
   an unknown name returns a clear "no such item" reply.
4. **Given** a customer adds a dish to their cart by name, **When** the cart is later summarized,
   **Then** the price charged is the one recorded in the menu database for that dish.

---

### User Story 2 - A confirmed order is recorded and given an order ID (Priority: P1)

A customer finishes ordering and confirms. Alongside the itemized summary they already receive, the
order is written into the restaurant's records as a complete order — every dish, quantity, unit
price, line total, and the order total — and an order ID identifying that record is produced. Staff
can later look the order up by that ID to see exactly what was ordered, and the ID travels with the
support ticket produced for the order.

**Why this priority**: Without a recorded order and an ID, a confirmed order exists only inside a
conversation that ends moments later — there is nothing for the kitchen to work from and nothing to
reference in a later refund or complaint. This is the second half of the feature and is equally
essential.

**Independent Test**: Run an ordering conversation, confirm an order, and check that an order ID is
returned with the summary; then look that ID up in the order records and confirm the stored items,
quantities, unit prices, line totals, and total match what the customer was shown.

**Acceptance Scenarios**:

1. **Given** a customer confirms an order containing 2 Kung Pao Chicken and 1 Hot and Sour Soup,
   **When** the order summary is produced, **Then** an order record exists containing both dishes
   with quantities 2 and 1, their unit prices, their line totals, and the order total, and an order
   ID identifying that record is returned with the summary.
2. **Given** two orders confirmed in separate conversations, **When** both are recorded, **Then** each
   receives a distinct order ID and neither record overwrites or alters the other.
3. **Given** a confirmed and recorded order, **When** the support ticket for that order is produced,
   **Then** the ticket carries the same order ID, and the same items, quantities, and total as the
   recorded order.
4. **Given** a recorded order, **When** it is retrieved by its order ID at any later time, **Then**
   the retrieved items, quantities, unit prices, line totals, and total are unchanged from when the
   order was confirmed — including if menu prices have since changed.

---

### User Story 3 - One consistent menu for the whole conversation (Priority: P2)

The menu is read once when a conversation's support run begins, and that same view of the menu is
used for every question, every item added, and the final priced summary in that run. A customer is
never quoted one price early in a conversation and charged another at confirmation because staff
edited the menu mid-conversation.

**Why this priority**: It protects the integrity of what Stories 1 and 2 deliver — a summary and an
order record whose prices match what the customer was actually quoted — but the system is already
useful without this guarantee being explicitly exercised.

**Independent Test**: Start a conversation and ask for a dish's price, change that dish's price in
the database mid-conversation, then finish and confirm the order; the summary and the recorded order
must both use the price quoted at the start of the run.

**Acceptance Scenarios**:

1. **Given** a customer is quoted a dish's price early in a conversation, **When** that price is
   changed in the database before the customer confirms, **Then** the summary and the recorded order
   use the originally quoted price.
2. **Given** a single conversation involving several menu questions and cart changes, **When** the run
   completes, **Then** the menu was read from the database once for that run rather than once per
   question.

---

### Edge Cases

- **Menu store unavailable or unreadable at run start**: the run stops immediately with a clear error
  naming the problem, rather than starting a conversation that will quote wrong prices or claim the
  restaurant has no menu.
- **Menu store reachable but holds no dishes**: menu questions return the existing "no items
  available" reply, and no dish can be added to a cart.
- **Order cannot be written when the customer confirms**: the customer is not told an order was placed
  under an ID that does not exist; the failure is surfaced, and no partial order record (for example,
  an order header with no items) is left behind.
- **Confirming with an empty cart**: no order record is created and no order ID is issued — the
  existing behavior of refusing to confirm an empty cart is unchanged.
- **A dish is renamed, repriced, or removed from the menu after an order is recorded**: previously
  recorded orders keep the names and prices they were placed with.
- **The same dish added several times**: the recorded order holds one line for that dish with the
  combined quantity, matching the summary the customer saw.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST source all menu data — dish names, prices, and ingredients — from a
  persistent menu data store, and MUST NOT read menu data from a bundled menu file at runtime.
- **FR-002**: The system MUST read the menu from the store exactly once at the start of a support run
  and use that single snapshot for every menu lookup, cart operation, and price calculation in that
  run.
- **FR-003**: The system MUST fail the run with a clear, actionable error when the menu store cannot
  be read at run start, rather than proceeding with an empty or partial menu.
- **FR-004**: Menu lookup behavior visible to customers — full-menu listing, inexact name matching,
  ambiguous-match prompting, and not-found replies — MUST remain unchanged from current behavior.
- **FR-005**: The system MUST record a complete order in the data store when a customer confirms an
  order, capturing every ordered dish with its quantity, unit price, and line total, plus the order
  total.
- **FR-006**: The system MUST assign each recorded order a unique identifier that is not reused across
  orders.
- **FR-007**: The order summary step MUST return the order ID of the recorded order as part of its
  output.
- **FR-008**: The support ticket produced for a confirmed order MUST include that order's ID alongside
  the items, quantities, and total it already carries.
- **FR-009**: Recorded orders MUST remain retrievable by their order ID after the conversation ends and
  after the system restarts.
- **FR-010**: A recorded order MUST preserve the dish names and prices in effect when it was placed,
  unaffected by later menu changes.
- **FR-011**: The system MUST NOT create an order record or issue an order ID when there is nothing in
  the customer's cart.
- **FR-012**: An order MUST be recorded either completely or not at all — a failure while recording
  MUST NOT leave a partial order in the store, and MUST NOT report a successful order to the customer.
- **FR-013**: The dish data currently held in the bundled menu file MUST be carried into the menu store
  so that existing menu answers and prices are unchanged on the first run after migration.
- **FR-014**: The order ID MUST be short enough for a customer to read aloud or type back accurately,
  and MUST NOT contain characters that are easily confused with one another. Looking an order up MUST
  tolerate the ways customers naturally retype a code — differing letter case, added or omitted
  separators, and substitution of visually similar characters.
- **FR-015**: Order IDs MUST NOT be sequential or otherwise predictable from another order's ID.

### Key Entities *(include if data involved)*

- **Menu Item**: A dish the restaurant offers. Has a name (unique, since customers refer to dishes by
  name), a price, and a list of ingredients used to answer ingredient and allergy questions.
- **Order**: A customer's confirmed order. Has a unique order ID, an order total, and the time it was
  placed. Composed of one or more order lines.
- **Order Line**: One dish within an order. Records the dish name, the quantity ordered, the unit price
  charged, and the line total. Values are captured at order time and do not follow later menu changes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of menu answers (full menu, dish lookup, cart pricing) reflect the current contents
  of the menu store, including dishes and prices changed since the application was last released.
- **SC-002**: Restaurant staff can change a dish's price or ingredients and have the change appear in
  customer conversations started afterward, with no code change and no new release.
- **SC-003**: 100% of confirmed, non-empty orders produce a retrievable order record and an order ID
  returned with the summary.
- **SC-004**: For every confirmed order, the items, quantities, unit prices, line totals, and total in
  the stored record match what the customer was shown, with zero discrepancies.
- **SC-005**: An order recorded before a system restart is retrievable by its ID after the restart,
  with identical contents.
- **SC-006**: No two orders ever share an order ID.
- **SC-008**: A customer can read their order ID off the screen and retype it — in any letter case,
  with or without the separator — and still reach their order on the first attempt.
- **SC-007**: Within a single conversation, a dish's quoted price never differs from the price charged
  for that dish on the final summary.

## Assumptions

- The store technology is SQLite, as directed in the feature request; it holds both the menu and the
  recorded orders in one database.
- The existing bundled menu file is used as the initial seed for the menu store and is no longer read
  during a conversation. Whether that file is deleted outright or kept only as seed data is an
  implementation decision left to planning.
- The menu store is populated and maintained outside of customer conversations; this feature adds no
  customer-facing or agent-facing way to create or edit menu items.
- Order IDs are opaque identifiers meaningful only as a reference — no date, sequence position, or
  order contents can be inferred from one. They are, however, designed to be spoken and retyped by
  customers, because the refund agent will identify an order by the ID the customer gives it
  (FR-014, FR-015).
- Because the refund agent is an unauthenticated conversational surface, the order ID is the only
  evidence a customer has that an order is theirs. It is treated accordingly: unguessable, but not a
  substitute for real authentication if the refund flow ever handles payment details.
- Orders are recorded for the ordering path only. The refund path is unchanged by this feature and
  does not create order records; building the refund agent's lookup on top of these IDs is a later
  feature, though this spec fixes the ID format that lookup will rely on.
- "Once at the start of the graph run" means once per support run (per conversation thread), not once
  per process lifetime — a later run picks up menu changes made since the earlier run.
- Recording an order is a terminal step of the ordering flow; the system does not support amending or
  cancelling an order record after it is written.
- Single-restaurant, single-database deployment; no multi-tenant or per-location menu separation is
  required.
- The database lives on local storage alongside the application; migrating to a networked database
  service is out of scope.
