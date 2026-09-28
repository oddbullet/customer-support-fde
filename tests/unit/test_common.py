import openai
import pytest
from langchain_openai import ChatOpenAI

from customer_support_fde import circuit_breaker
from customer_support_fde.nodes import common


@pytest.fixture(autouse=True)
def _reset_circuit():
    circuit_breaker.reset_circuit()
    yield
    circuit_breaker.reset_circuit()


# Without a fallback configured, build_llm() keeps ChatOpenAI's built-in retries and
# raises once they are exhausted, exactly as before the circuit breaker. (regression)
def test_build_llm_retries_failing_api_calls_before_giving_up(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("FALLBACK_MODEL", raising=False)
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


# An unset, empty, or whitespace-only FALLBACK_MODEL disables the circuit breaker, so
# build_llm() returns a plain ChatOpenAI. (regression)
@pytest.mark.parametrize("fallback", [None, "", "   "])
def test_build_llm_returns_plain_chat_model_without_fallback(monkeypatch, fallback):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    if fallback is None:
        monkeypatch.delenv("FALLBACK_MODEL", raising=False)
    else:
        monkeypatch.setenv("FALLBACK_MODEL", fallback)

    assert isinstance(common.build_llm(), ChatOpenAI)


# With FALLBACK_MODEL set, build_llm() wraps a retrying primary, a single-attempt
# probe of the same model, and a retrying fallback around the shared breaker. (base)
def test_build_llm_returns_circuit_breaker_when_fallback_set(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "primary/model")
    monkeypatch.setenv("FALLBACK_MODEL", "fallback/model")

    llm = common.build_llm()

    assert isinstance(llm, circuit_breaker.CircuitBreakerLLM)
    assert llm.primary.model_name == "primary/model"
    assert llm.primary.max_retries == common.LLM_MAX_RETRIES == 3
    assert llm.probe.model_name == "primary/model"
    assert llm.probe.max_retries == 0
    assert llm.fallback.model_name == "fallback/model"
    assert llm.fallback.max_retries == 3
    assert (llm.primary_model, llm.fallback_model) == ("primary/model", "fallback/model")
    assert llm.breaker is circuit_breaker._BREAKER


# With OPENROUTER_MODEL unset, the circuit breaker's primary and probe fall back to
# DEFAULT_MODEL. (edge)
def test_build_llm_circuit_breaker_primary_defaults_to_default_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setenv("FALLBACK_MODEL", "fallback/model")

    llm = common.build_llm()

    assert llm.primary.model_name == common.DEFAULT_MODEL
    assert llm.probe.model_name == common.DEFAULT_MODEL
