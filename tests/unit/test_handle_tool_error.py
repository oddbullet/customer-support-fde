from customer_support_fde.nodes.common import TOOL_ERROR_MESSAGE, handle_tool_error


# The message sent back to an agent after a tool exception is a fixed instruction to
# retry the same call without telling the customer; the customer only ever sees the
# CLI's coded tool-limit warning. (happy)
def test_tool_error_message_tells_agent_to_retry_silently():
    assert TOOL_ERROR_MESSAGE == (
        "The tool call failed with a temporary error. Call the same tool again with "
        "the same arguments. Do not mention this error to the customer."
    )


# An unexpected tool exception is replaced by the fixed retry instruction, so its
# internal details never reach the model. (failure)
def test_handle_tool_error_hides_exception_details():
    assert handle_tool_error(RuntimeError("internal-detail")) == TOOL_ERROR_MESSAGE
