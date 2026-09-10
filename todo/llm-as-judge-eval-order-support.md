# LLM-as-Judge Eval Coverage — Order/Support Agent (002)

Deferred out of scope for the initial 002 implementation (`research.md` §9: reply wording is validated manually via `quickstart.md` for now, not by automated eval). This list captures what an LLM-as-judge layer should cover if/when it's added back, since replies are model-composed (native tool-calling design, not fixed templates) and can no longer be asserted with exact-string tests.

## Faithfulness to tool results (no hallucination)

- Full menu listing includes every item `get_menu` actually returned — none omitted, none invented (FR-002, SC-002)
- Item detail reply includes all three of name, price, *and* ingredients for a `found` result — not a partial answer (FR-001, SC-001)
- No fabricated menu items, prices, or ingredients ever appear in a reply that aren't backed by an actual tool result (general anti-hallucination guard behind FR-005)

## The three hard "MUST" behaviors that lost their template guarantee

- Not-found replies clearly say the item isn't available — never a guess dressed up as an answer (FR-005, SC-005)
- Tie replies list the actual tied candidate names and ask which one — never silently pick one (FR-005a, SC-005)
- Every successful add is followed by some form of "anything else?" — this is the one FR-006 explicitly calls a MUST, and it's now the least-guaranteed thing in the whole design

## New capabilities this design enables (never tested before, since they didn't exist under the template approach)

- Recommendation quality: answer is grounded in actual menu data (ingredients/price), reasonably responsive to what was asked ("something spicy," "vegetarian options"), and doesn't invent attributes the menu data doesn't have (e.g. a spice level field that isn't in `menu.json`)
- Multi-item messages: every item the customer mentioned gets acknowledged in the reply — none silently dropped, none double-counted

## Cart/state-accuracy in the reply text itself

- Add confirmations use the *resolved* canonical item name, not an echo of the customer's typo/partial phrasing
- Cart summary the model is given each turn (`research.md` §4's "brief cart summary") is reflected correctly across turns — no items forgotten or duplicated in what the model says back
- The empty-cart "nothing to confirm yet" case reads as an acknowledgment, not as if something was confirmed (FR-007 edge case)

## Scope discipline

- Model doesn't take an action the customer didn't actually ask for (e.g. adding something they only mentioned in passing)
- An out-of-scope question mid-conversation gets redirected gracefully rather than answered with invented information (hours, location, policies — none of which are in `menu.json`)

## Next step, when picked back up

Turn this into a concrete rubric (pass/fail criteria per bullet) and slot it into `research.md` §9 as a follow-on testing layer, plus corresponding tasks in `tasks.md`.
