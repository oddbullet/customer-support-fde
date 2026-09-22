import openai
import pytest

from customer_support_fde.nodes import common

def test_build_llm_retries_failing_api_calls_before_giving_up(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(openai._base_client.time, "sleep", lambda _seconds: None)

    llm = common.build_llm()

    attempts = []

    def _always_fail(self, request, **kwargs):
        attempts.append(request)
        raise RuntimeError("OpenRouter unreachable")

    monkeypatch.setattr(type(llm.root_client._client), "send", _always_fail)

    with pytest.raises(openai.APIConnectionError):
        llm.invoke("hello")

    # One initial attempt plus at least three retries.
    assert len(attempts) >= 4
