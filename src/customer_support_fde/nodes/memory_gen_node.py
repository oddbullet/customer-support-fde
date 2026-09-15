import logging
import os

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from customer_support_fde import db
from customer_support_fde.state import SupportState

_logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-4o-mini"

_EXTRACTION_INSTRUCTIONS = """\
You are maintaining a customer's stored food preferences for a restaurant's \
account records, based on their order-support conversation. Read the \
conversation that follows and identify explicit statements about food \
likes, dislikes, or allergies — including one-off per-order customization \
requests (e.g. "no onions on this one"); treat those as dislikes/customization \
preferences, not allergies.

If you are given a message stating the customer's current stored \
preferences, combine it with anything newly found into one rewritten, \
coherent passage — never simply append. Preserve every previously known \
fact (especially allergies) unless a newer statement in this conversation \
explicitly contradicts it, in which case the newer statement wins. When the \
conversation itself contains contradictory statements about the same \
thing, keep only the customer's most recent statement.

Distinguish allergies from everything else in your reply — lead with an \
explicit "Allergies: ..." clause when one or more allergies exist, followed \
by likes/dislikes/customizations, so a future feature reading this text \
back can treat allergies as closer to a hard constraint and everything \
else as a guideline.

Reply with exactly "None" (and nothing else) only when there is nothing to \
record at all: no prior preferences were supplied AND nothing new was \
found in the conversation. Otherwise always reply with the full passage \
(even if it ends up identical to the prior one).
"""


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        model=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
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
    context.extend(state["messages"])

    try:
        reply = _build_llm().invoke(context).content.strip()
        if reply.lower() == "none":
            return {}
        db.update_account_preferences(account_number, reply)
    except Exception:
        _logger.warning(
            "Failed to extract/persist account preferences", exc_info=True
        )

    return {}
