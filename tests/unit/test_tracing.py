import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from customer_support_fde import tracing


@pytest.fixture
def exporter():
    return InMemorySpanExporter()


@pytest.fixture
def provider(exporter):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider


@pytest.fixture
def test_logger(provider):
    # A private logger with only the Phoenix handler, so the test sees exactly what the
    # handler does without touching the root logger.
    logger = logging.getLogger("customer_support_fde.test_tracing")
    logger.handlers = [tracing.PhoenixLogHandler(tracer_provider=provider)]
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    yield logger
    logger.handlers = []
    logger.propagate = True


def _raise_and_capture() -> ValueError:
    try:
        raise ValueError("db exploded at C:/secret/path.db")
    except ValueError as exc:
        return exc


# A warning logged inside an active span is added to that span as a log event with
# its severity, logger name, and message. (happy)
def test_log_inside_span_adds_event_to_current_span(provider, exporter, test_logger):
    with provider.get_tracer("t").start_as_current_span("node"):
        test_logger.warning("Failed to condense conversation history")

    (span,) = exporter.get_finished_spans()
    assert span.name == "node"
    (event,) = [e for e in span.events if e.name == "log"]
    assert event.attributes["log.severity"] == "WARNING"
    assert event.attributes["log.logger"] == test_logger.name
    assert event.attributes["log.message"] == "Failed to condense conversation history"


# A log call carrying exc_info records the exception on the span and marks the span
# as an error, so the traceback is visible in Phoenix. (happy)
def test_log_with_exc_info_records_exception_and_error_status(
    provider, exporter, test_logger
):
    exc = _raise_and_capture()

    with provider.get_tracer("t").start_as_current_span("tools"):
        test_logger.warning("Tool call failed", exc_info=exc)

    (span,) = exporter.get_finished_spans()
    exception_events = [e for e in span.events if e.name == "exception"]
    assert len(exception_events) == 1
    assert exception_events[0].attributes["exception.type"] == "ValueError"
    assert "C:/secret/path.db" in exception_events[0].attributes["exception.message"]
    assert span.status.status_code == StatusCode.ERROR


# An ERROR-level log with no exception still marks the span as an error. (edge)
def test_error_level_log_without_exception_sets_error_status(
    provider, exporter, test_logger
):
    with provider.get_tracer("t").start_as_current_span("cli"):
        test_logger.error("Tool-call limit reached")

    (span,) = exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR


# A plain warning with no exception leaves the span's status unset, so degraded-but-
# handled paths don't show as failures. (edge)
def test_plain_warning_does_not_set_error_status(provider, exporter, test_logger):
    with provider.get_tracer("t").start_as_current_span("node"):
        test_logger.warning("Heads up")

    (span,) = exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.UNSET


# A log call made outside any span is not lost: the handler opens a short "log" span
# for it. (edge)
def test_log_outside_span_creates_log_span(provider, exporter, test_logger):
    exc = _raise_and_capture()

    test_logger.error("Unexpected error", exc_info=exc)

    (span,) = exporter.get_finished_spans()
    assert span.name == "log"
    assert any(e.name == "log" for e in span.events)
    assert any(e.name == "exception" for e in span.events)
    assert span.status.status_code == StatusCode.ERROR


@pytest.fixture
def clean_root_logger():
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    root.handlers = []
    yield root
    root.handlers = saved_handlers
    root.setLevel(saved_level)


# configure_logging() attaches exactly one Phoenix handler to the root logger at
# WARNING, even when called more than once. (edge)
def test_configure_logging_installs_single_phoenix_handler(clean_root_logger):
    tracing.configure_logging()
    tracing.configure_logging()

    phoenix_handlers = [
        h for h in clean_root_logger.handlers if isinstance(h, tracing.PhoenixLogHandler)
    ]
    assert len(phoenix_handlers) == 1
    assert clean_root_logger.level == logging.WARNING


# Once logging is configured, a warning with a traceback is never written to the
# terminal (stdout or stderr). (failure, regression) — regression guard for tracebacks leaking to
# the customer through Python's lastResort handler.
def test_configured_logging_writes_nothing_to_terminal(clean_root_logger, capsys):
    tracing.configure_logging()

    logging.getLogger("customer_support_fde.nodes.common").warning(
        "Tool call failed", exc_info=_raise_and_capture()
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# setup_tracing() configures logging even when no Phoenix endpoint is set, so the
# terminal stays clean without Phoenix too. (edge)
def test_setup_tracing_configures_logging_without_phoenix(
    clean_root_logger, monkeypatch, capsys
):
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)

    tracing.setup_tracing()
    logging.getLogger("customer_support_fde.tickets").error(
        "Failed to write ticket file", exc_info=_raise_and_capture()
    )

    assert any(
        isinstance(h, tracing.PhoenixLogHandler) for h in clean_root_logger.handlers
    )
    captured = capsys.readouterr()
    assert captured.err == ""
