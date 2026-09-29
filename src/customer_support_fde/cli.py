import sys
from pathlib import Path

from customer_support_fde import db, interactive, restaurant_time
from customer_support_fde.graph import build_graph
from customer_support_fde.tracing import setup_tracing

from dotenv import load_dotenv

load_dotenv()
setup_tracing()

GRAPH_FILENAME = "graph.png"


def run(argv: list[str] | None = None) -> int:
    # Model-composed replies can contain characters (em dashes, curly quotes)
    # that the default console codec on Windows can't encode; without this,
    # printing such a reply crashes the CLI mid-conversation.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    argv = sys.argv[1:] if argv is None else argv

    if "--init-db" in argv:
        try:
            count = db.init_database()
            print(f"Initialized {db.database_path()} with {count} menu items.")
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if "--set-tz" in argv:
        index = argv.index("--set-tz") + 1
        zone = argv[index].lower() if index < len(argv) else ""
        if zone not in restaurant_time.US_TIMEZONES:
            options = ", ".join(restaurant_time.US_TIMEZONES)
            print(f"Error: choose a timezone from: {options}", file=sys.stderr)
            return 1
        try:
            db.set_restaurant_timezone(restaurant_time.US_TIMEZONES[zone])
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Restaurant timezone set to {zone} ({restaurant_time.US_TIMEZONES[zone]}).")
        return 0

    if "--graph" in argv:
        try:
            output_path = Path(GRAPH_FILENAME)
            png_bytes = build_graph().get_graph().draw_mermaid_png()
            output_path.write_bytes(png_bytes)
            print(f"Wrote graph to {output_path.resolve()}")
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    return interactive.run_interactive()
