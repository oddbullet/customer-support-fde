import time
from typing import Any, Callable, Literal

import openai
from opentelemetry import trace

CIRCUIT_COOLDOWN_SECONDS = 60


def _get_tracer() -> trace.Tracer:
    return trace.get_tracer(__name__)


class ModelUnavailableError(Exception):
    pass


def is_retryable(exc: BaseException) -> bool:
    # Mirrors openai._base_client._should_retry: these are the failures ChatOpenAI
    # has already retried LLM_MAX_RETRIES times before raising.
    if isinstance(exc, openai.APIConnectionError):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code in (408, 409, 429) or exc.status_code >= 500
    return False


class CircuitBreaker:
    def __init__(
        self,
        cooldown_seconds: float = CIRCUIT_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self.state: Literal["closed", "open"] = "closed"
        self.opened_at: float | None = None

    def effective_state(self) -> Literal["closed", "open", "half_open"]:
        if self.state == "closed":
            return "closed"
        if self.clock() - self.opened_at >= self.cooldown_seconds:
            return "half_open"
        return "open"

    def record_open(self) -> None:
        self.state = "open"
        self.opened_at = self.clock()

    def record_close(self) -> None:
        self.state = "closed"
        self.opened_at = None


_BREAKER = CircuitBreaker()


def reset_circuit() -> None:
    _BREAKER.record_close()
    _BREAKER.clock = time.monotonic


class CircuitBreakerLLM:
    # Wraps the three chat models build_llm() needs when FALLBACK_MODEL is set and
    # exposes the subset of the chat-model interface the agents actually use.
    def __init__(
        self,
        primary: Any,
        probe: Any,
        fallback: Any,
        primary_model: str,
        fallback_model: str,
        breaker: CircuitBreaker,
    ):
        self.primary = primary
        self.probe = probe
        self.fallback = fallback
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.breaker = breaker

    def _apply(self, method: str, *args, **kwargs) -> "CircuitBreakerLLM":
        return CircuitBreakerLLM(
            primary=getattr(self.primary, method)(*args, **kwargs),
            probe=getattr(self.probe, method)(*args, **kwargs),
            fallback=getattr(self.fallback, method)(*args, **kwargs),
            primary_model=self.primary_model,
            fallback_model=self.fallback_model,
            breaker=self.breaker,
        )

    def bind_tools(self, *args, **kwargs) -> "CircuitBreakerLLM":
        return self._apply("bind_tools", *args, **kwargs)

    def with_structured_output(self, *args, **kwargs) -> "CircuitBreakerLLM":
        return self._apply("with_structured_output", *args, **kwargs)

    def invoke(self, input, config=None, **kwargs):
        # The span's default exception handling records the error and sets ERROR status.
        with _get_tracer().start_as_current_span("llm.circuit_breaker") as span:
            span.set_attribute("circuit.state_before", self.breaker.effective_state())
            try:
                return self._invoke(span, input, config, **kwargs)
            finally:
                span.set_attribute("circuit.state_after", self.breaker.effective_state())

    def _invoke(self, span, input, config=None, **kwargs):
        state = self.breaker.effective_state()
        if state == "open":
            return self._invoke_fallback(span, input, config, **kwargs)

        # Closed: the retrying primary. Half-open: a single-attempt probe of it.
        attempt = self.primary if state == "closed" else self.probe
        try:
            result = attempt.invoke(input, config, **kwargs)
        except Exception as exc:
            if not is_retryable(exc):
                raise
            span.set_attribute("circuit.primary_error", f"{type(exc).__name__}: {exc}")
            self.breaker.record_open()
            span.add_event("circuit_opened")
            return self._invoke_fallback(span, input, config, **kwargs)

        if state == "half_open":
            self.breaker.record_close()
            span.add_event("circuit_closed")
        span.set_attribute("circuit.fallback_used", False)
        span.set_attribute("circuit.model_answered", self.primary_model)
        return result

    def _invoke_fallback(self, span, input, config=None, **kwargs):
        span.set_attribute("circuit.fallback_used", True)
        try:
            result = self.fallback.invoke(input, config, **kwargs)
        except Exception as exc:
            if not is_retryable(exc):
                raise
            raise ModelUnavailableError("primary and fallback models unavailable") from exc
        span.set_attribute("circuit.model_answered", self.fallback_model)
        return result
