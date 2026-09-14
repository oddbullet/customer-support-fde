import os

from phoenix.otel import register


def setup_tracing() -> None:
    if not os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"):
        return
    register(
        project_name=os.environ.get("PHOENIX_PROJECT_NAME", "customer-support-fde"),
        batch=True,
        auto_instrument=True,
        verbose=False,
    )
