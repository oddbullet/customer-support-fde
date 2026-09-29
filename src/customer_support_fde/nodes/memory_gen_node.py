import logging

from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from customer_support_fde import db
from customer_support_fde.nodes.common import build_llm as _build_llm
from customer_support_fde.state import SupportState

_logger = logging.getLogger(__name__)

_EXTRACTION_INSTRUCTIONS = """\
You are maintaining a customer's stored food preferences for a restaurant's \
account records, based on their order-support conversation. Read the \
conversation that follows and identify explicit statements about food \
likes, dislikes, or allergies — including one-off per-order customization \
requests (e.g. "no onions on this one"); treat those as dislikes/customization \
preferences, not allergies.

Only extract statements the customer themselves made about food. Ignore \
everything else in the conversation — including the assistant's own \
replies, order confirmations, pickup or delivery time estimates, \
greetings, and any other logistics or small talk. None of that belongs in \
a preferences record, no matter how prominent it is in the conversation.

If you are given a message stating the customer's current stored \
preferences, combine it with anything newly found into one rewritten, \
coherent passage — never simply append. Preserve every previously known \
fact (especially allergies) unless a newer statement in this conversation \
explicitly contradicts it, in which case the newer statement wins. When the \
conversation itself contains contradictory statements about the same \
thing, keep only the customer's most recent statement.

If you are given a summary of the earlier conversation, treat the customer \
statements it records as part of the conversation.

Distinguish allergies from everything else in your reply — lead with an \
explicit "Allergies: ..." clause when one or more allergies exist, followed \
by likes/dislikes/customizations, so a future feature reading this text \
back can treat allergies as closer to a hard constraint and everything \
else as a guideline.

Leave the preferences field null when there is nothing to record at all: \
no prior preferences were supplied AND nothing new was found in the \
conversation. Otherwise always populate it with the full passage (even if \
it ends up identical to the prior one).
"""


class _PreferenceExtraction(BaseModel):
    preferences: str | None = Field(
        default=None,
        description=(
            "The customer's combined food likes, dislikes, allergies, and "
            "per-order customization preferences, as one coherent passage "
            "leading with an explicit 'Allergies: ...' clause when any "
            "exist. Null when there is nothing to record — never order "
            "logistics, confirmations, or other non-preference content."
        ),
    )


def memory_gen_node(state: SupportState) -> SupportState:
    account_number = state.get("account_number")
    if not account_number:
        return {}

    context = [SystemMessage(content=_EXTRACTION_INSTRUCTIONS)]
    prior_preferences = state.get("account_preferences")
    if prior_preferences is not None:
        context.append(
            SystemMessage(
                content=f"Customer's current stored preferences: {prior_preferences}"
            )
        )
    summary = state.get("order_conversation_summary")
    if summary is not None:
        context.append(
            SystemMessage(content=f"Summary of earlier conversation:\n{summary}")
        )
    context.extend(state["messages"])

    try:
        result = (
            _build_llm().with_structured_output(_PreferenceExtraction).invoke(context)
        )
        if result.preferences is None:
            return {}
        preferences = result.preferences.strip()
        if not preferences:
            return {}
        db.update_account_preferences(account_number, preferences)
    except Exception:
        _logger.warning(
            "Failed to extract/persist account preferences", exc_info=True
        )

    return {}
