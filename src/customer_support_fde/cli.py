import sys

from customer_support_fde import db, interactive
from customer_support_fde.tracing import setup_tracing

from dotenv import load_dotenv

load_dotenv()
setup_tracing()


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

    return interactive.run_interactive()
