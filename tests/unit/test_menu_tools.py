from customer_support_fde import db
from customer_support_fde.tools.menu_tools import (
    cart_total,
    get_menu,
    get_menu_item,
    price_for_item,
    resolve_menu_item,
)

SAMPLE_MENU = [
    {
        "name": "Kung Pao Chicken",
        "price": 12.95,
        "ingredients": ["chicken", "peanuts", "dried chili"],
    },
    {
        "name": "Mapo Tofu",
        "price": 11.50,
        "ingredients": ["tofu", "ground pork", "chili bean paste"],
    },
    {
        "name": "Beef Noodle Soup",
        "price": 10.95,
        "ingredients": ["beef", "noodle", "scallion"],
    },
    {
        "name": "Beef Noodle Bowl",
        "price": 9.95,
        "ingredients": ["beef", "noodle", "bean sprout"],
    },
    {
        "name": "Spring Rolls",
        "price": 6.95,
        "ingredients": ["cabbage", "carrot", "wheat wrapper"],
    },
]


# An exact name match resolves directly to that menu item. (base)
def test_exact_name_match_resolves_found():
    match = resolve_menu_item("Kung Pao Chicken", SAMPLE_MENU)

    assert match.status == "found"
    assert match.item["name"] == "Kung Pao Chicken"


# Matching ignores case, so a lowercase query still resolves the exact item. (edge)
def test_case_insensitive_exact_match_resolves_found():
    match = resolve_menu_item("kung pao chicken", SAMPLE_MENU)

    assert match.status == "found"
    assert match.item["name"] == "Kung Pao Chicken"


# A substring query resolves when it uniquely identifies one menu item. (edge)
def test_partial_substring_match_resolves_found_when_unique():
    match = resolve_menu_item("Mapo", SAMPLE_MENU)

    assert match.status == "found"
    assert match.item["name"] == "Mapo Tofu"


# Fuzzy matching tolerates a minor typo and still resolves the closest item. (edge)
def test_minor_typo_resolves_found():
    match = resolve_menu_item("Sprng Rolls", SAMPLE_MENU)

    assert match.status == "found"
    assert match.item["name"] == "Spring Rolls"


# A query with no candidate above the similarity cutoff resolves as not found. (edge)
def test_not_found_when_nothing_meets_the_cutoff():
    match = resolve_menu_item("Pizza", SAMPLE_MENU)

    assert match.status == "not_found"


# Two items scoring equally at the top resolve as a tie listing both candidates. (edge)
def test_tie_when_two_items_score_equally_at_the_top():
    match = resolve_menu_item("Beef Noodle", SAMPLE_MENU)

    assert match.status == "tie"
    assert set(match.candidates) == {"Beef Noodle Soup", "Beef Noodle Bowl"}


# Sanity-checks that the real menu.json data, seeded into the database, is
# present and well-formed. (base)
def test_seeded_menu_json_has_at_least_five_well_formed_items(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_database(path)

    menu = db.load_menu(path)

    assert len(menu) >= 5
    for item in menu:
        assert isinstance(item["name"], str) and item["name"]
        assert isinstance(item["price"], (int, float)) and item["price"] > 0
        assert isinstance(item["ingredients"], list) and item["ingredients"]


# get_menu reads the menu from state["menu"] rather than loading it itself. (base)
def test_get_menu_reads_menu_from_state():
    rendered = get_menu.func(state={"menu": SAMPLE_MENU})

    for item in SAMPLE_MENU:
        assert item["name"] in rendered


# An empty state["menu"] renders the existing "no items available" text. (edge)
def test_get_menu_empty_state_menu_renders_no_items_available():
    rendered = get_menu.func(state={"menu": []})

    assert rendered == "There are no items available on the menu right now."


# get_menu_item reads the menu from state["menu"] rather than loading it itself. (base)
def test_get_menu_item_reads_menu_from_state():
    rendered = get_menu_item.func(name="Mapo Tofu", state={"menu": SAMPLE_MENU})

    assert "Mapo Tofu" in rendered


# get_menu_item reports a not-found message (not a stack trace or empty
# string) when no menu item matches, exercising the tool's own render path
# rather than only resolve_menu_item's match object. (edge)
def test_get_menu_item_not_found_reports_no_match_message():
    rendered = get_menu_item.func(name="Pizza", state={"menu": SAMPLE_MENU})

    assert "No menu item matches" in rendered


# An exact canonical-name match returns that menu entry's price. (base)
def test_price_for_item_returns_price_on_exact_match():
    assert price_for_item("Kung Pao Chicken", SAMPLE_MENU) == 12.95


# A name absent from the menu returns None rather than raising. (edge)
def test_price_for_item_returns_none_when_name_not_on_menu():
    assert price_for_item("Peking Duck", SAMPLE_MENU) is None


# A near-miss name that resolve_menu_item would fuzzy-match returns None
# instead of another item's price, guarding the mispricing risk in
# research.md §4. (regression)
def test_price_for_item_does_not_fuzzy_match_near_miss_name():
    assert resolve_menu_item("Sprng Rolls", SAMPLE_MENU).status == "found"

    assert price_for_item("Sprng Rolls", SAMPLE_MENU) is None


# A single item at quantity 1 totals to exactly that item's price. (base)
def test_cart_total_single_item_quantity_one():
    assert cart_total({"Kung Pao Chicken": 1}, SAMPLE_MENU) == 12.95


# Multiple distinct items at varying quantities sum to price times quantity
# across every line. (base)
def test_cart_total_multiple_items_varying_quantities():
    cart = {"Kung Pao Chicken": 2, "Mapo Tofu": 1, "Spring Rolls": 3}

    assert cart_total(cart, SAMPLE_MENU) == 12.95 * 2 + 11.50 + 6.95 * 3


# An empty cart returns None rather than 0.0, matching
# build_order_summary's existing "no total" convention. (edge)
def test_cart_total_empty_cart_returns_none():
    assert cart_total({}, SAMPLE_MENU) is None


# The total always rounds up (never down) on a fractional-cent sum, matching
# the ROUND_CEILING rule build_order_summary already relies on. (edge)
def test_cart_total_rounds_up_on_fractional_cent():
    fractional_cent_menu = [{"name": "Item A", "price": 4.321, "ingredients": []}]

    assert cart_total({"Item A": 1}, fractional_cent_menu) == 4.33
