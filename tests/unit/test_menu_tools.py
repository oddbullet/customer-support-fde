from customer_support_fde.tools.menu_tools import (
    _load_menu,
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


# Sanity-checks that the real menu.json data is present and well-formed. (base)
def test_real_menu_json_has_at_least_five_well_formed_items():
    menu = _load_menu()

    assert len(menu) >= 5
    for item in menu:
        assert isinstance(item["name"], str) and item["name"]
        assert isinstance(item["price"], (int, float)) and item["price"] > 0
        assert isinstance(item["ingredients"], list) and item["ingredients"]


# An exact canonical-name match returns that menu entry's price. (base)
def test_price_for_item_returns_price_on_exact_match():
    assert price_for_item("Kung Pao Chicken", SAMPLE_MENU) == 12.95


# A name absent from the menu returns None rather than raising. (edge)
def test_price_for_item_returns_none_when_name_not_on_menu():
    assert price_for_item("Peking Duck", SAMPLE_MENU) is None


# An empty menu list returns None for any name. (edge)
def test_price_for_item_returns_none_for_empty_menu():
    assert price_for_item("Kung Pao Chicken", []) is None


# A near-miss name that resolve_menu_item would fuzzy-match returns None
# instead of another item's price, guarding the mispricing risk in
# research.md §4. (regression)
def test_price_for_item_does_not_fuzzy_match_near_miss_name():
    assert resolve_menu_item("Sprng Rolls", SAMPLE_MENU).status == "found"

    assert price_for_item("Sprng Rolls", SAMPLE_MENU) is None
