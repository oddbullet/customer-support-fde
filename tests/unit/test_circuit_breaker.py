import io

import httpx
import openai
import pytest
from langchain_openai import ChatOpenAI
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from customer_support_fde import circuit_breaker, interactive, messages
from customer_support_fde.nodes import common

from _cli_fakes import (
    RESOLVED_STATE,
    FakeInterrupt,
    buffer_console,
    record_warnings,
    scripted_graph,
)

_REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def _status_error(cls, status: int):
    return cls("boom", response=httpx.Response(status, request=_REQUEST), body=None)


def _validation_error() -> ValidationError:
    class _Shape(BaseModel):
        value: int

    try:
        _Shape(value="not-an-int")
    except ValidationError as exc:
        return exc
    raise AssertionError("expected ValidationError")


# is_retryable() returns True exactly for the failures the openai client itself
# retries, and False for everything else. (happy)
@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (openai.APIConnectionError(request=_REQUEST), True),
        (openai.APITimeoutError(request=_REQUEST), True),
        (_status_error(openai.APIStatusError, 408), True),
        (_status_error(openai.ConflictError, 409), True),
        (_status_error(openai.RateLimitError, 429), True),
        (_status_error(openai.InternalServerError, 500), True),
        (_status_error(openai.InternalServerError, 502), True),
        (_status_error(openai.InternalServerError, 503), True),
        (_status_error(openai.InternalServerError, 504), True),
        (_status_error(openai.BadRequestError, 400), False),
        (_status_error(openai.AuthenticationError, 401), False),
        (_status_error(openai.PermissionDeniedError, 403), False),
        (_status_error(openai.NotFoundError, 404), False),
        (_status_error(openai.UnprocessableEntityError, 422), False),
        (_validation_error(), False),
        (ValueError("bad"), False),
        (RuntimeError("bad"), False),
    ],
)
def test_is_retryable_matches_openai_client_retry_rules(exc, expected):
    assert circuit_breaker.is_retryable(exc) is expected


class FakeRunnable:
    def __init__(self, outcome=None, error: BaseException | None = None, calls=None):
        self.outcome = outcome
        self.error = error
        self.inputs: list = []
        self.calls = calls if calls is not None else []

    def invoke(self, input, config=None, **kwargs):
        self.inputs.append(input)
        if self.error is not None:
            raise self.error
        return self.outcome

    def bind_tools(self, *args, **kwargs):
        self.calls.append(("bind_tools", args, kwargs))
        return FakeRunnable(self.outcome, self.error, self.calls)

    def with_structured_output(self, *args, **kwargs):
        self.calls.append(("with_structured_output", args, kwargs))
        return FakeRunnable(self.outcome, self.error, self.calls)


def _retryable() -> BaseException:
    return _status_error(openai.InternalServerError, 503)


def _non_retryable() -> BaseException:
    return _status_error(openai.AuthenticationError, 401)




@pytest.fixture
def clock():
    return {"now": 0.0}


def _wrapper(clock, primary=None, probe=None, fallback=None):
    breaker = circuit_breaker.CircuitBreaker(clock=lambda: clock["now"])
    return circuit_breaker.CircuitBreakerLLM(
        primary=primary or FakeRunnable("primary reply"),
        probe=probe or FakeRunnable("probe reply"),
        fallback=fallback or FakeRunnable("fallback reply"),
        primary_model="p",
        fallback_model="f",
        breaker=breaker,
    )


# Closed circuit, primary succeeds: its reply is returned, the fallback is never
# called, and the circuit stays closed. (happy)
def test_closed_primary_success_returns_primary_reply(clock):
    llm = _wrapper(clock)

    assert llm.invoke("hi") == "primary reply"
    assert llm.fallback.inputs == []
    assert llm.breaker.effective_state() == "closed"


# Closed circuit, primary exhausts its retries: the same input object is re-sent to
# the fallback, whose reply is returned, and the circuit opens. (failure)
def test_closed_primary_retryable_failure_falls_back_and_opens(clock):
    llm = _wrapper(clock, primary=FakeRunnable(error=_retryable()))
    request = ["the", "request"]

    assert llm.invoke(request) == "fallback reply"
    assert llm.fallback.inputs[0] is request
    assert llm.breaker.effective_state() == "open"


# Both models fail with retryable errors: ModelUnavailableError is raised, chained to
# the fallback's error, and the circuit is open. (failure)
def test_closed_both_models_retryable_failure_raises_model_unavailable(clock):
    fallback_error = _retryable()
    llm = _wrapper(
        clock,
        primary=FakeRunnable(error=_retryable()),
        fallback=FakeRunnable(error=fallback_error),
    )

    with pytest.raises(circuit_breaker.ModelUnavailableError) as excinfo:
        llm.invoke("hi")

    assert excinfo.value.__cause__ is fallback_error
    assert llm.breaker.effective_state() == "open"


# A non-retryable fallback error (e.g. bad API key) is re-raised unchanged instead of
# being mapped to ModelUnavailableError. (failure)
def test_closed_fallback_non_retryable_error_is_reraised(clock):
    fallback_error = _non_retryable()
    llm = _wrapper(
        clock,
        primary=FakeRunnable(error=_retryable()),
        fallback=FakeRunnable(error=fallback_error),
    )

    with pytest.raises(openai.AuthenticationError) as excinfo:
        llm.invoke("hi")

    assert excinfo.value is fallback_error


# A non-retryable primary error is re-raised, never triggers the fallback, and leaves
# the circuit closed. (failure)
def test_closed_primary_non_retryable_error_is_reraised_without_fallback(clock):
    primary_error = _non_retryable()
    llm = _wrapper(clock, primary=FakeRunnable(error=primary_error))

    with pytest.raises(openai.AuthenticationError) as excinfo:
        llm.invoke("hi")

    assert excinfo.value is primary_error
    assert llm.fallback.inputs == []
    assert llm.breaker.effective_state() == "closed"


# bind_tools and with_structured_output apply the same call to all three inner
# runnables and return a new wrapper sharing the same breaker. (happy)
@pytest.mark.parametrize("method", ["bind_tools", "with_structured_output"])
def test_wrapper_passes_binding_calls_to_every_inner_runnable(clock, method):
    llm = _wrapper(clock)

    bound = getattr(llm, method)(["tool"], strict=True)

    assert isinstance(bound, circuit_breaker.CircuitBreakerLLM)
    assert bound is not llm
    assert bound.breaker is llm.breaker
    for inner in (llm.primary, llm.probe, llm.fallback):
        assert inner.calls == [(method, (["tool"],), {"strict": True})]
    assert (bound.primary_model, bound.fallback_model) == ("p", "f")


def _opened_wrapper(clock, **runnables):
    llm = _wrapper(clock, **runnables)
    llm.breaker.record_open()
    return llm


# Within the cool-down, requests skip the primary (and the probe) and go straight to
# the fallback; the circuit stays open. (failure)
def test_open_circuit_skips_primary_within_cooldown(clock):
    llm = _opened_wrapper(clock)
    clock["now"] = 30

    assert llm.invoke("hi") == "fallback reply"
    assert llm.primary.inputs == []
    assert llm.probe.inputs == []
    assert llm.breaker.effective_state() == "open"


# While open, a retryable fallback failure raises ModelUnavailableError without
# restarting the cool-down. (failure)
def test_open_circuit_fallback_failure_raises_model_unavailable(clock):
    llm = _opened_wrapper(clock, fallback=FakeRunnable(error=_retryable()))
    clock["now"] = 30

    with pytest.raises(circuit_breaker.ModelUnavailableError):
        llm.invoke("hi")

    assert llm.breaker.opened_at == 0


# Exactly at the end of the cool-down the circuit is half-open: the single-attempt
# probe answers and the circuit closes. (edge)
def test_half_open_probe_success_closes_circuit(clock):
    llm = _opened_wrapper(clock)
    clock["now"] = 60

    assert llm.invoke("hi") == "probe reply"
    assert len(llm.probe.inputs) == 1
    assert llm.primary.inputs == []
    assert llm.fallback.inputs == []
    assert llm.breaker.effective_state() == "closed"


# A retryable probe failure is served by the fallback and reopens the circuit with a
# fresh cool-down. (failure)
def test_half_open_probe_retryable_failure_reopens_circuit(clock):
    llm = _opened_wrapper(clock, probe=FakeRunnable(error=_retryable()))
    clock["now"] = 60

    assert llm.invoke("hi") == "fallback reply"
    assert llm.breaker.effective_state() == "open"
    assert llm.breaker.opened_at == 60


# A non-retryable probe failure is re-raised without using the fallback, and the
# circuit stays open with its original cool-down. (edge)
def test_half_open_probe_non_retryable_failure_is_reraised(clock):
    probe_error = _non_retryable()
    llm = _opened_wrapper(clock, probe=FakeRunnable(error=probe_error))
    clock["now"] = 60

    with pytest.raises(openai.AuthenticationError) as excinfo:
        llm.invoke("hi")

    assert excinfo.value is probe_error
    assert llm.fallback.inputs == []
    assert llm.breaker.opened_at == 0


# Just before the cool-down ends the circuit is still open and the probe is not
# tried. (edge)
def test_circuit_stays_open_just_before_cooldown_ends(clock):
    llm = _opened_wrapper(clock)
    clock["now"] = 59.9

    assert llm.invoke("hi") == "fallback reply"
    assert llm.probe.inputs == []
    assert llm.breaker.effective_state() == "open"


# reset_circuit() returns the shared breaker to closed. (happy)
def test_reset_circuit_closes_shared_breaker():
    circuit_breaker.SHARED_BREAKER.record_open()

    circuit_breaker.reset_circuit()

    assert circuit_breaker.SHARED_BREAKER.effective_state() == "closed"
    assert circuit_breaker.SHARED_BREAKER.opened_at is None


@pytest.fixture
def spans(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(circuit_breaker, "_get_tracer", lambda: provider.get_tracer("test"))
    return exporter


def _only_span(exporter):
    (span,) = exporter.get_finished_spans()
    assert span.name == "llm.circuit_breaker"
    return span


def _event_names(span) -> list[str]:
    return [event.name for event in span.events]


# A primary success is traced as a closed-circuit request answered by the primary,
# with no fallback and no primary error. (happy)
def test_span_records_primary_success(clock, spans):
    _wrapper(clock).invoke("hi")

    span = _only_span(spans)
    assert span.attributes["circuit.state_before"] == "closed"
    assert span.attributes["circuit.state_after"] == "closed"
    assert span.attributes["circuit.fallback_used"] is False
    assert span.attributes["circuit.model_answered"] == "p"
    assert "circuit.primary_error" not in span.attributes


# A fallback after a primary failure is traced with the primary's error, the model
# that answered, and a circuit_opened event. (failure)
def test_span_records_fallback_and_circuit_opening(clock, spans):
    _wrapper(clock, primary=FakeRunnable(error=_retryable())).invoke("hi")

    span = _only_span(spans)
    assert span.attributes["circuit.state_before"] == "closed"
    assert span.attributes["circuit.state_after"] == "open"
    assert span.attributes["circuit.fallback_used"] is True
    assert span.attributes["circuit.model_answered"] == "f"
    assert "InternalServerError" in span.attributes["circuit.primary_error"]
    assert _event_names(span) == ["circuit_opened"]


# A successful half-open probe is traced as the primary resuming, with a
# circuit_closed event. (edge)
def test_span_records_probe_closing_circuit(clock, spans):
    llm = _opened_wrapper(clock)
    clock["now"] = 60

    llm.invoke("hi")

    span = _only_span(spans)
    assert span.attributes["circuit.state_before"] == "half_open"
    assert span.attributes["circuit.state_after"] == "closed"
    assert span.attributes["circuit.model_answered"] == "p"
    assert _event_names(span) == ["circuit_closed"]


# When both models fail, the span has no answering model and an ERROR status. (failure)
def test_span_records_both_models_failing(clock, spans):
    from opentelemetry.trace import StatusCode

    llm = _wrapper(
        clock,
        primary=FakeRunnable(error=_retryable()),
        fallback=FakeRunnable(error=_retryable()),
    )

    with pytest.raises(circuit_breaker.ModelUnavailableError):
        llm.invoke("hi")

    span = _only_span(spans)
    assert span.attributes["circuit.fallback_used"] is True
    assert "circuit.model_answered" not in span.attributes
    assert span.attributes["circuit.state_after"] == "open"
    assert span.status.status_code == StatusCode.ERROR


# A request served straight from the fallback while open records no primary error,
# since the primary was never tried. (edge)
def test_span_records_open_circuit_request(clock, spans):
    llm = _opened_wrapper(clock)
    clock["now"] = 30

    llm.invoke("hi")

    span = _only_span(spans)
    assert span.attributes["circuit.state_before"] == "open"
    assert span.attributes["circuit.fallback_used"] is True
    assert "circuit.primary_error" not in span.attributes


# Without a fallback configured, build_llm() keeps ChatOpenAI's built-in retries and
# raises once they are exhausted, exactly as before the circuit breaker. (failure, regression)
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
# build_llm() returns a plain ChatOpenAI. (edge, regression)
@pytest.mark.parametrize("fallback", [None, "", "   "])
def test_build_llm_returns_plain_chat_model_without_fallback(monkeypatch, fallback):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    if fallback is None:
        monkeypatch.delenv("FALLBACK_MODEL", raising=False)
    else:
        monkeypatch.setenv("FALLBACK_MODEL", fallback)

    assert isinstance(common.build_llm(), ChatOpenAI)

# With FALLBACK_MODEL set, build_llm() wraps a retrying primary, a single-attempt
# probe of the same model, and a retrying fallback around the shared breaker. (happy)
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
    assert llm.breaker is circuit_breaker.SHARED_BREAKER

# With OPENROUTER_MODEL unset, the circuit breaker's primary and probe fall back to
# DEFAULT_MODEL. (edge)
def test_build_llm_circuit_breaker_primary_defaults_to_default_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setenv("FALLBACK_MODEL", "fallback/model")

    llm = common.build_llm()

    assert llm.primary.model_name == common.DEFAULT_MODEL
    assert llm.probe.model_name == common.DEFAULT_MODEL


# The model-retry prompt is a fixed, friendly message that asks for Enter to retry,
# with no internal details. (happy)
def test_model_retry_prompt_text():
    assert messages.MODEL_RETRY_PROMPT == (
        "Sorry, something went wrong on our end. Press Enter to try again."
    )


# The CLI allows 2 manual retries per step when both models are unavailable. (happy)
def test_model_retry_limit_is_2():
    assert interactive.MODEL_RETRY_LIMIT == 2


# When both models are unavailable, the retry prompt is shown, one Enter is read, and
# the failed step is replayed with invoke(None) on the same thread. (failure)
def test_run_conversation_retries_failed_step_after_model_unavailable(monkeypatch):
    warnings = record_warnings(monkeypatch)
    stdin = io.StringIO("\n")
    monkeypatch.setattr(interactive.sys, "stdin", stdin)
    console = buffer_console()
    graph, calls = scripted_graph(
        [interactive.ModelUnavailableError("down"), RESOLVED_STATE]
    )

    result = interactive._run_conversation(console, graph, "what's on the menu?")

    assert result is RESOLVED_STATE
    assert warnings == [messages.MODEL_RETRY_PROMPT]
    assert stdin.read() == ""
    assert calls[1][0] is None
    assert calls[0][1] == calls[1][1]


# Two outages in a row are both retried on the same thread, and the step succeeds on
# the second retry. (edge)
def test_run_conversation_retries_up_to_the_limit(monkeypatch):
    warnings = record_warnings(monkeypatch)
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("\n\n"))
    graph, calls = scripted_graph(
        [
            interactive.ModelUnavailableError("down"),
            interactive.ModelUnavailableError("still down"),
            RESOLVED_STATE,
        ]
    )

    result = interactive._run_conversation(buffer_console(), graph, "hi")

    assert result is RESOLVED_STATE
    assert warnings == [messages.MODEL_RETRY_PROMPT] * 2
    assert [call[0] for call in calls[1:]] == [None, None]
    assert len({call[1] for call in calls}) == 1


# Once the 2 manual retries are used up, the next outage is re-raised instead of
# prompting again, so run_interactive shows the generic message. (failure)
def test_run_conversation_gives_up_after_retry_limit(monkeypatch):
    warnings = record_warnings(monkeypatch)
    stdin = io.StringIO("\n\nleftover\n")
    monkeypatch.setattr(interactive.sys, "stdin", stdin)
    graph, calls = scripted_graph(
        [
            interactive.ModelUnavailableError("down"),
            interactive.ModelUnavailableError("still down"),
            interactive.ModelUnavailableError("down for good"),
        ]
    )

    with pytest.raises(interactive.ModelUnavailableError):
        interactive._run_conversation(buffer_console(), graph, "hi")

    assert len(calls) == 3
    assert warnings == [messages.MODEL_RETRY_PROMPT] * 2
    assert stdin.read() == "leftover\n"


# A model outage while resuming an interrupt is retried the same way, and the
# conversation then continues through its next interrupt normally. (failure)
def test_run_conversation_retries_after_outage_on_interrupt_resume(monkeypatch):
    record_warnings(monkeypatch)
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("2\n\nyes\n"))
    graph, calls = scripted_graph(
        [
            {"__interrupt__": [FakeInterrupt("Reply with 1, 2, or 3.")]},
            interactive.ModelUnavailableError("down"),
            {"__interrupt__": [FakeInterrupt("What would you like to order?")]},
            RESOLVED_STATE,
        ]
    )

    result = interactive._run_conversation(buffer_console(), graph, "I'd like to order")

    assert result is RESOLVED_STATE
    assert isinstance(calls[1][0], Command) and calls[1][0].resume == "2"
    assert calls[2][0] is None
    assert isinstance(calls[3][0], Command) and calls[3][0].resume == "yes"


# Errors other than ModelUnavailableError are not caught by _run_conversation, so they
# still reach run_interactive's generic error handler. (failure, regression)
def test_run_conversation_does_not_catch_other_errors(monkeypatch):
    warnings = record_warnings(monkeypatch)
    graph, _calls = scripted_graph([RuntimeError("boom")])

    with pytest.raises(RuntimeError, match="boom"):
        interactive._run_conversation(buffer_console(), graph, "hi")

    assert warnings == []


# The raw ModelUnavailableError text is never shown to the customer. (failure)
def test_run_conversation_hides_model_unavailable_details(monkeypatch):
    monkeypatch.setattr(interactive.sys, "stdin", io.StringIO("\n"))
    console = buffer_console()
    graph, _calls = scripted_graph(
        [interactive.ModelUnavailableError("internal provider detail"), RESOLVED_STATE]
    )

    interactive._run_conversation(console, graph, "hi")

    output = console.file.getvalue()
    assert messages.MODEL_RETRY_PROMPT in output
    assert "internal provider detail" not in output
