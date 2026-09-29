"""Customer-facing error texts, shared so every failure reads the same way.

Technical details never go here; they are logged, and logging is routed to Phoenix.
"""

_ORDER_GUIDANCE = (
    "Please exit the application and try again. If the problem continues, please "
    "order at the counter."
)

_ASK_GUIDANCE = (
    "Please exit the application and try again. If the problem continues, please "
    "ask at the counter."
)

GENERIC_ERROR_MESSAGE = "Sorry, something went wrong on our end. " + _ORDER_GUIDANCE

ORDER_NOT_PLACED_MESSAGE = (
    "Sorry, something went wrong on our end and your order was not placed. "
    + _ORDER_GUIDANCE
)

MODEL_RETRY_PROMPT = "Sorry, something went wrong on our end. Press Enter to try again."

# Returned to the refund agent as tool results, so it can tell the customer plainly
# that nothing went through.
ORDER_LOOKUP_FAILED = (
    "I couldn't look up that order because of a problem on our end. " + _ASK_GUIDANCE
)

REFUND_NOT_SUBMITTED = (
    "Your refund request was not submitted because of a problem on our end. "
    + _ASK_GUIDANCE
)

COMPLAINT_NOT_RECORDED = (
    "Your complaint was not recorded because of a problem on our end. " + _ASK_GUIDANCE
)
