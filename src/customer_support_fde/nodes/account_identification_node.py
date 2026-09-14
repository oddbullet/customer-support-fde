from langgraph.types import interrupt

from customer_support_fde import db
from customer_support_fde.state import SupportState

PRIMARY_MENU = (
    "1) Use an existing account\n"
    "2) Continue without an account\n"
    "3) Sign up for a new account\n"
    "Reply with 1, 2, or 3."
)

ACCOUNT_NUMBER_PROMPT = "What's your account number?"

RECOVERY_MENU = (
    "I couldn't find an account with that number.\n"
    "1) Try entering it again\n"
    "2) Sign up for a new account\n"
    "3) Continue without an account\n"
    "Reply with 1, 2, or 3."
)

_MENU_ANSWERS = {"1", "2", "3"}


def _no_account() -> SupportState:
    return {"account_number": None, "account_preferences": None}


def _use_existing_account() -> SupportState:
    while True:
        raw_reply = str(interrupt(ACCOUNT_NUMBER_PROMPT)).strip()
        account = db.get_account(raw_reply)
        if account is not None:
            return {
                "account_number": account["account_number"],
                "account_preferences": account["preferences"],
            }

        answer = str(interrupt(RECOVERY_MENU)).strip()
        while answer not in _MENU_ANSWERS:
            answer = str(interrupt(RECOVERY_MENU)).strip()

        if answer == "1":
            continue
        if answer == "2":
            return _sign_up()
        return _no_account()


def _sign_up() -> SupportState:
    account_number = db.create_account()
    interrupt(
        f"Your new account number is {db.format_account_number(account_number)}. "
        "Please save it for future visits."
    )
    return {"account_number": account_number, "account_preferences": None}


def account_identification_node(state: SupportState) -> SupportState:
    answer = str(interrupt(PRIMARY_MENU)).strip()
    while answer not in _MENU_ANSWERS:
        answer = str(interrupt(PRIMARY_MENU)).strip()

    if answer == "1":
        return _use_existing_account()
    if answer == "2":
        return _no_account()
    return _sign_up()
