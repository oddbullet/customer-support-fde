import json
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from importlib import resources
from typing import Literal

from langchain_core.tools import tool

MATCH_CUTOFF = 0.6
TIE_EPSILON = 1e-9

MenuItem = dict[str, object]


@dataclass(frozen=True)
class MenuMatch:
    status: Literal["found", "tie", "not_found"]
    item: MenuItem | None = None
    candidates: list[str] = field(default_factory=list)


def _score(query: str, item_name: str) -> float:
    query_cf = query.casefold()
    name_cf = item_name.casefold()
    if query_cf and query_cf in name_cf:
        return 1.0
    return SequenceMatcher(None, query_cf, name_cf).ratio()


def resolve_menu_item(name: str, menu: list[MenuItem]) -> MenuMatch:
    scored = [(_score(name, item["name"]), item) for item in menu]
    candidates = [(score, item) for score, item in scored if score >= MATCH_CUTOFF]
    if not candidates:
        return MenuMatch(status="not_found")

    top_score = max(score for score, _ in candidates)
    top = [item for score, item in candidates if abs(score - top_score) <= TIE_EPSILON]
    if len(top) > 1:
        return MenuMatch(status="tie", candidates=[item["name"] for item in top])
    return MenuMatch(status="found", item=top[0])


def price_for_item(name: str, menu: list[MenuItem]) -> float | None:
    for item in menu:
        if item["name"] == name:
            return item["price"]
    return None


@lru_cache(maxsize=1)
def _load_menu() -> list[MenuItem]:
    data = (
        resources.files("customer_support_fde.menu")
        .joinpath("menu.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(data)


def _render_item(item: MenuItem) -> str:
    ingredients = ", ".join(item["ingredients"])
    return f"{item['name']} (${item['price']:.2f}): {ingredients}"


def _render_menu(menu: list[MenuItem]) -> str:
    if not menu:
        return "There are no items available on the menu right now."
    return "\n".join(_render_item(item) for item in menu)


def _render_match(match: MenuMatch) -> str:
    if match.status == "found":
        return _render_item(match.item)
    if match.status == "tie":
        names = ", ".join(match.candidates)
        return f"Multiple menu items match that name: {names}. Which one did you mean?"
    return "No menu item matches that name."


@tool
def get_menu() -> str:
    """Return every item currently on the menu, with price and ingredients.

    Returns:
        str: A newline-separated listing of every menu item (name, price,
        ingredients), or a message saying the menu is empty.
    """
    return _render_menu(_load_menu())


@tool
def get_menu_item(name: str) -> str:
    """Look up details for one menu item by name (fuzzy-matched against the menu).

    Args:
        name: The menu item name to search for. Matched against the menu
            with fuzzy string matching, so it need not be exact.

    Returns:
        str: The matched item's name, price, and ingredients; a prompt
        listing the candidates if multiple items tie; or a not-found
        message if nothing matches.
    """
    return _render_match(resolve_menu_item(name, _load_menu()))
