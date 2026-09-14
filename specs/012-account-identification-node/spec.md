# Feature Specification: Customer Account Identification Node

**Feature Branch**: `012-account-identification-node`

**Created**: 2026-09-14

**Status**: Draft

**Input**: User description: "- I want the order / support agent to be able to pull in information about the user if they have an account. Things that should be recorded are what they like / dislike and allergy.
- This node should sit between router and order node. A deterministic node that has three option: (1) I have an account that I want to use, (2) I don't, and (3) Sign Up for an Account.
- (1) Ask the user to input their account number
- (3) Generate an account number and return it to the user
- All of this information should be saved in the SQLite database. Note, that there is no agent that actually does the summary currently. And that is okay. THat will be implemented next."

## Clarifications

### Session 2026-09-14

- Q: How should an account's likes, dislikes, and allergies actually get captured/recorded? → A: Out of scope for this feature — this feature only creates the account/number and its (initially empty) profile; a later feature will implement the mechanism that actually populates likes/dislikes/allergies (mirroring how the ticket summary agent is already a known follow-up in this project).
- Q: Should looking up an existing account require anything beyond the account number itself? → A: Account number only — matches the existing no-authentication trust model already used for order lookups in this system.
- Q: What should each of likes, dislikes, and allergies actually store — a list of short items, or a single free-text note per field? → A: A single combined free-text "preferences" field (one paragraph covering likes, dislikes, and allergies together), not separate per-field or list-shaped data. This paragraph is intended to be produced by a future conversation-summarization agent and used directly as context for the order/support agent, so it doesn't need to be parsed into structured data.
- Q: When the account step asks the customer to pick among the three options, how should it recognize which one they picked? → A: A numbered/lettered menu — the step presents the three options as a numbered/lettered list, and the customer replies with the number/letter of their choice, so the match is deterministic and unambiguous.
- Q: If a customer replies with something that isn't a valid menu number/letter, what should the step do? → A: Re-prompt the customer with the same three-option menu until they give a valid number/letter.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Returning customer uses their existing account (Priority: P1)

A customer who already has an account wants the order/support agent to know their stored preferences (likes, dislikes, and allergies) for this conversation, so they get answered and served with that context in mind.

**Why this priority**: This is the core value of the feature — giving the order/support agent access to a known customer's profile — and every other option in this feature exists to reach or route around this outcome.

**Independent Test**: Create an account ahead of time with a known account number, start a new conversation, select "I have an account," enter that account number, and confirm the conversation proceeds to the order/support agent with that account's stored profile available to it.

**Acceptance Scenarios**:

1. **Given** a customer starting a new conversation that has been routed to order/support, **When** the account step runs, **Then** it presents exactly three choices: use an existing account, continue without an account, or sign up for a new account.
2. **Given** a customer selects "I have an account," **When** they enter an account number that matches an existing account, **Then** they proceed to the order/support agent with that account's stored preferences text available to it.
3. **Given** a customer selects "I have an account," **When** they enter an account number that does not match any existing account, **Then** they are told the account wasn't found and are offered the choice to re-enter a number, sign up for a new account instead, or continue without one.

---

### User Story 2 - New customer signs up for an account (Priority: P2)

A first-time customer wants to create an account so that a future visit can recognize them and use their stored preferences.

**Why this priority**: Sign-up is what makes User Story 1 possible for new customers over time, but it is independently valuable and testable without needing an existing account first.

**Independent Test**: Select "sign up for an account," confirm a new unique account number is generated and returned to the customer, and confirm that number can be looked up successfully (with an empty profile) in a separate, later conversation.

**Acceptance Scenarios**:

1. **Given** a customer selects "sign up for an account," **When** the step processes the request, **Then** a new, unique account number is generated, an account record is created for it, and the account number is returned to the customer to save for future visits.
2. **Given** a newly created account, **When** that account number is looked up in a later, separate conversation, **Then** the account is found successfully with no preferences text yet recorded.

---

### User Story 3 - Customer continues without an account (Priority: P3)

A customer who doesn't have or doesn't want an account should be able to proceed straight to ordering, exactly as they can today.

**Why this priority**: This preserves the current experience for customers uninterested in accounts. It's lowest priority because it's the "do nothing extra" path, but it must be explicit so the deterministic step always has a defined outcome for every customer.

**Independent Test**: Select "I don't have one," and confirm the conversation proceeds directly to the order/support agent with no account created and no profile data attached.

**Acceptance Scenarios**:

1. **Given** a customer selects "I don't have an account," **When** the step processes the request, **Then** they proceed to the order/support agent with no account associated with the conversation, and no account record is created or modified.

---

### Edge Cases

- An account number entered with different casing, extra spacing, or stray punctuation should still be recognized if it matches an existing account, consistent with how order numbers are already normalized before lookup.
- An entered value that isn't shaped like a valid account number at all (wrong length or characters) is treated the same as "not found," with the same recovery choices offered (re-enter, sign up, or continue without).
- A customer who selects "sign up" despite already having an account gets a new, separate account and account number; this feature does not attempt to detect or merge duplicates.
- Because lookup trusts the account number alone (per Clarifications), anyone who has or guesses a given account number can have that account's stored profile used for their conversation — this mirrors the existing trust model already used for order-number lookups in this system, and adding stronger authentication is out of scope here.
- A conversation where the customer ends up without an identified account (by choice, or after a not-found account number) proceeds through the order/support agent exactly as it behaves today, with no profile data attached.
- A customer's reply to the three-option menu that isn't a valid number/letter is not treated as any of the three options; the step re-presents the same menu until the customer replies with a valid number/letter.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST run a deterministic account-identification step between the router agent and the order/support agent for every conversation that is routed to order/support.
- **FR-002**: This step MUST present the customer with exactly three options — (1) use an existing account, (2) continue without an account, and (3) sign up for a new account — as a numbered/lettered menu, and MUST determine the customer's choice from the number/letter they reply with.
- **FR-003**: When the customer selects option (1), the system MUST prompt them to enter their account number.
- **FR-004**: When an entered account number matches an existing account, the system MUST retrieve that account's stored preferences text (a single free-text field covering likes, dislikes, and allergies together) and make it available to the order/support agent for the remainder of the conversation.
- **FR-005**: When an entered account number does not match any existing account, the system MUST inform the customer it wasn't found and let them choose to re-enter a number, sign up for a new account instead, or continue without one.
- **FR-006**: When the customer selects option (3), the system MUST generate a new account number that is not already in use, create a corresponding account record with no preferences text yet recorded, and return the generated account number to the customer.
- **FR-007**: When the customer selects option (2), the system MUST proceed directly to the order/support agent without creating, modifying, or attaching any account to the conversation.
- **FR-008**: The system MUST persist every account — its account number and its preferences text (empty or populated) — as a single free-text field in the SQLite database, so it can be retrieved in later, separate conversations.
- **FR-009**: Account lookup MUST succeed based on the account number alone; the system MUST NOT require or check any other identifying information (e.g., name) to retrieve an account's profile.
- **FR-010**: Account numbers MUST be unique across all accounts.
- **FR-011**: The account-identification step's outcome MUST be driven directly and only by the customer's selected menu number/letter among the three options (and, for option 1, by whether the entered account number matches an existing account) rather than by open-ended interpretation of free-form conversation.
- **FR-012**: When the customer's reply to the three-option menu is not a valid number/letter for any of the three options, the system MUST re-present the same menu rather than guessing, defaulting, or advancing to any of the three options.

### Key Entities

- **Customer Account**: A unique account number identifying the account, plus a single stored preferences text field — one free-text paragraph covering likes, dislikes, and allergies together (empty until a future feature populates it). Persisted independently of any single conversation or order, and retrievable across separate conversations.
- **Account Identification Step**: The deterministic step between the router agent and the order/support agent. It offers the three options described above, and results in the conversation either carrying an identified account's profile, carrying a newly created (empty) account's number, or carrying no account at all.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A returning customer with a correctly entered, existing account number reaches the order/support agent with their stored preferences attached in a single entry, with no retries needed.
- **SC-002**: 100% of newly signed-up accounts can be successfully looked up by their returned account number in a later, separate conversation.
- **SC-003**: Every conversation that reaches the order/support agent has an unambiguous account state — either a specific identified/created account, or explicitly none — with no conversation reaching order/support in an unresolved state.
- **SC-004**: Customers who select "continue without an account" experience the order/support flow identically to how it behaves today, with no added steps or behavior changes.

## Assumptions

- Populating an account's preferences text (e.g., a future summarization agent producing a paragraph of likes, dislikes, and allergies from the conversation) is not part of this feature. This feature only establishes accounts, their (initially empty) preferences field, and the ability to create and look them up. Actually populating that text is planned as a follow-up feature, the same way the ticket summary agent is already a known, separate follow-up in this project.
- The preferences field is unstructured free text, not parsed into individual likes/dislikes/allergy items; it is intended to be used directly as context for the order/support agent rather than programmatically inspected.
- Account lookup trusts the account number alone, mirroring the existing no-additional-authentication pattern already used for order-number lookups in this system.
- Account numbers are short and easy for a customer to read back and re-enter, consistent with the format already used for order numbers.
- This feature does not add any way to view, edit, delete, or transfer an existing account's data beyond creating it and looking it up.
- A single account may be used across many separate orders and conversations over time; accounts are independent of any specific order.
- Only one account (or none) may be associated with a given conversation; switching accounts mid-conversation is out of scope.
