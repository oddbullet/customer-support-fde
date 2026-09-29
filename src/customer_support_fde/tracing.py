import logging
import os

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from phoenix.otel import register


class PhoenixLogHandler(logging.Handler):
    # Phoenix only ingests spans, so each log record is attached to the current span
    # (or a short "log" span when none is active) instead of being printed.
    def __init__(self, tracer_provider: trace.TracerProvider | None = None):
        super().__init__()
        self._tracer = trace.get_tracer(__name__, tracer_provider=tracer_provider)

    def emit(self, record: logging.LogRecord) -> None:
        span = trace.get_current_span()
        if span.is_recording():
            self._record(span, record)
            return
        with self._tracer.start_as_current_span("log") as log_span:
            self._record(log_span, record)

    def _record(self, span: trace.Span, record: logging.LogRecord) -> None:
        span.add_event(
            "log",
            {
                "log.severity": record.levelname,
                "log.logger": record.name,
                "log.message": record.getMessage(),
            },
        )
        exc = record.exc_info[1] if record.exc_info else None
        if exc is not None:
            span.record_exception(exc)
        if exc is not None or record.levelno >= logging.ERROR:
            span.set_status(Status(StatusCode.ERROR, record.getMessage()))

    def handleError(self, record: logging.LogRecord) -> None:
        # A failure inside the handler must never reach the customer's terminal.
        pass


def configure_logging() -> None:
    # With a handler on the root logger, Python never falls back to printing
    # warnings and tracebacks to stderr, which is the customer's terminal.
    root = logging.getLogger()
    if not any(isinstance(h, PhoenixLogHandler) for h in root.handlers):
        root.addHandler(PhoenixLogHandler())
    root.setLevel(logging.WARNING)


def setup_tracing() -> None:
    configure_logging()
    if not os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"):
        return
    register(
        project_name=os.environ.get("PHOENIX_PROJECT_NAME", "customer-support-fde"),
        batch=True,
        auto_instrument=True,
        verbose=False,
    )
