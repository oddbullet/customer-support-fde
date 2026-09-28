import httpx
import openai
import pytest
from pydantic import BaseModel, ValidationError

from customer_support_fde import circuit_breaker

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
# retries, and False for everything else. (base)
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


# ModelUnavailableError is an ordinary Exception subclass. (base)
def test_model_unavailable_error_is_an_exception():
    assert issubclass(circuit_breaker.ModelUnavailableError, Exception)


# The circuit's cool-down is fixed at 60 seconds. (base)
def test_circuit_cooldown_is_sixty_seconds():
    assert circuit_breaker.CIRCUIT_COOLDOWN_SECONDS == 60


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


@pytest.fixture(autouse=True)
def _reset_circuit():
    circuit_breaker.reset_circuit()
    yield
    circuit_breaker.reset_circuit()


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
# called, and the circuit stays closed. (base)
def test_closed_primary_success_returns_primary_reply(clock):
    llm = _wrapper(clock)

    assert llm.invoke("hi") == "primary reply"
    assert llm.fallback.inputs == []
    assert llm.breaker.effective_state() == "closed"


# Closed circuit, primary exhausts its retries: the same input object is re-sent to
# the fallback, whose reply is returned, and the circuit opens. (base)
def test_closed_primary_retryable_failure_falls_back_and_opens(clock):
    llm = _wrapper(clock, primary=FakeRunnable(error=_retryable()))
    request = ["the", "request"]

    assert llm.invoke(request) == "fallback reply"
    assert llm.fallback.inputs[0] is request
    assert llm.breaker.effective_state() == "open"


# Both models fail with retryable errors: ModelUnavailableError is raised, chained to
# the fallback's error, and the circuit is open. (error)
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
# being mapped to ModelUnavailableError. (error)
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
# the circuit closed. (error)
def test_closed_primary_non_retryable_error_is_reraised_without_fallback(clock):
    primary_error = _non_retryable()
    llm = _wrapper(clock, primary=FakeRunnable(error=primary_error))

    with pytest.raises(openai.AuthenticationError) as excinfo:
        llm.invoke("hi")

    assert excinfo.value is primary_error
    assert llm.fallback.inputs == []
    assert llm.breaker.effective_state() == "closed"


# bind_tools and with_structured_output apply the same call to all three inner
# runnables and return a new wrapper sharing the same breaker. (base)
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
# the fallback; the circuit stays open. (base)
def test_open_circuit_skips_primary_within_cooldown(clock):
    llm = _opened_wrapper(clock)
    clock["now"] = 30

    assert llm.invoke("hi") == "fallback reply"
    assert llm.primary.inputs == []
    assert llm.probe.inputs == []
    assert llm.breaker.effective_state() == "open"


# While open, a retryable fallback failure raises ModelUnavailableError without
# restarting the cool-down. (error)
def test_open_circuit_fallback_failure_raises_model_unavailable(clock):
    llm = _opened_wrapper(clock, fallback=FakeRunnable(error=_retryable()))
    clock["now"] = 30

    with pytest.raises(circuit_breaker.ModelUnavailableError):
        llm.invoke("hi")

    assert llm.breaker.effective_state() == "open"
    assert llm.breaker.opened_at == 0


# Exactly at the end of the cool-down the circuit is half-open: the single-attempt
# probe answers and the circuit closes. (base)
def test_half_open_probe_success_closes_circuit(clock):
    llm = _opened_wrapper(clock)
    clock["now"] = 60

    assert llm.invoke("hi") == "probe reply"
    assert len(llm.probe.inputs) == 1
    assert llm.primary.inputs == []
    assert llm.fallback.inputs == []
    assert llm.breaker.effective_state() == "closed"


# A retryable probe failure is served by the fallback and reopens the circuit with a
# fresh cool-down. (error)
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
    assert llm.breaker.state == "open"
    assert llm.breaker.opened_at == 0


# Just before the cool-down ends the circuit is still open and the probe is not
# tried. (edge)
def test_circuit_stays_open_just_before_cooldown_ends(clock):
    llm = _opened_wrapper(clock)
    clock["now"] = 59.9

    assert llm.invoke("hi") == "fallback reply"
    assert llm.probe.inputs == []
    assert llm.breaker.effective_state() == "open"


# reset_circuit() returns the shared breaker to closed. (base)
def test_reset_circuit_closes_shared_breaker():
    circuit_breaker._BREAKER.record_open()

    circuit_breaker.reset_circuit()

    assert circuit_breaker._BREAKER.effective_state() == "closed"
    assert circuit_breaker._BREAKER.opened_at is None


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
# with no fallback and no primary error. (base)
def test_span_records_primary_success(clock, spans):
    _wrapper(clock).invoke("hi")

    span = _only_span(spans)
    assert span.attributes["circuit.state_before"] == "closed"
    assert span.attributes["circuit.state_after"] == "closed"
    assert span.attributes["circuit.fallback_used"] is False
    assert span.attributes["circuit.model_answered"] == "p"
    assert "circuit.primary_error" not in span.attributes


# A fallback after a primary failure is traced with the primary's error, the model
# that answered, and a circuit_opened event. (base)
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
# circuit_closed event. (base)
def test_span_records_probe_closing_circuit(clock, spans):
    llm = _opened_wrapper(clock)
    clock["now"] = 60

    llm.invoke("hi")

    span = _only_span(spans)
    assert span.attributes["circuit.state_before"] == "half_open"
    assert span.attributes["circuit.state_after"] == "closed"
    assert span.attributes["circuit.model_answered"] == "p"
    assert _event_names(span) == ["circuit_closed"]


# When both models fail, the span has no answering model and an ERROR status. (error)
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
