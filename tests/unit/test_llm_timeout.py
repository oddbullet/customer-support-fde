from customer_support_fde.nodes import common


# Without a fallback, each request attempt is capped at LLM_TIMEOUT_SECONDS instead of
# the openai client's 600-second default. (base)
def test_build_llm_sets_request_timeout_without_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("FALLBACK_MODEL", raising=False)

    llm = common.build_llm()

    assert llm.request_timeout == common.LLM_TIMEOUT_SECONDS == 40


# With FALLBACK_MODEL set, the primary, probe, and fallback all cap each request
# attempt at LLM_TIMEOUT_SECONDS, so a hung primary opens the circuit. (base)
def test_build_llm_sets_request_timeout_on_all_circuit_breaker_models(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("FALLBACK_MODEL", "fallback/model")

    llm = common.build_llm()

    assert llm.primary.request_timeout == common.LLM_TIMEOUT_SECONDS == 40
    assert llm.probe.request_timeout == 40
    assert llm.fallback.request_timeout == 40


# Without a fallback, each request's output is capped at LLM_MAX_OUTPUT_TOKENS, so a
# runaway generation stops instead of streaming past the per-read timeout. (base)
def test_build_llm_caps_output_tokens_without_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("FALLBACK_MODEL", raising=False)

    llm = common.build_llm()

    assert llm.max_tokens == common.LLM_MAX_OUTPUT_TOKENS == 4000


# With FALLBACK_MODEL set, the primary, probe, and fallback all cap output. (base)
def test_build_llm_caps_output_tokens_on_all_circuit_breaker_models(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("FALLBACK_MODEL", "fallback/model")

    llm = common.build_llm()

    assert llm.primary.max_tokens == 4000
    assert llm.probe.max_tokens == 4000
    assert llm.fallback.max_tokens == 4000
