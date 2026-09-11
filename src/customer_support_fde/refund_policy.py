from dataclasses import dataclass
from datetime import datetime, timedelta

REFUND_WINDOW_HOURS = 48

_MESSAGES = {
    "outside_window": (
        f"This order was placed more than {REFUND_WINDOW_HOURS} hours ago, so it's "
        "outside our refund window."
    ),
    "return_declined": (
        "Since a substitute dish arrived, we need you to confirm you'll return it before "
        "we can process a refund."
    ),
    # Covers both FR-005 denial framings: the problem is with an item that was correctly
    # delivered (quality, temperature, timing, change of mind), or no item was reported
    # undelivered at all. evaluate() has no channel to tell these apart — both leave
    # `undelivered` empty — so they share one reason code and one message.
    "no_undelivered_items": (
        "Refunds only apply when an ordered item wasn't received. We didn't identify any "
        "item on this order that wasn't delivered, so there's nothing to refund."
    ),
}


@dataclass(frozen=True)
class PolicyDecision:
    eligible: bool
    reason: str | None
    message: str


def evaluate(
    order: dict,
    undelivered: list[dict],
    substitute_received: bool,
    return_confirmed: bool,
    now: datetime,
) -> PolicyDecision:
    created_at = datetime.fromisoformat(order["created_at"])
    if now - created_at > timedelta(hours=REFUND_WINDOW_HOURS):
        return PolicyDecision(False, "outside_window", _MESSAGES["outside_window"])

    if not undelivered:
        return PolicyDecision(
            False, "no_undelivered_items", _MESSAGES["no_undelivered_items"]
        )

    if substitute_received and not return_confirmed:
        return PolicyDecision(False, "return_declined", _MESSAGES["return_declined"])

    return PolicyDecision(True, None, "Your refund request is eligible.")
