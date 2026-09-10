from customer_support_fde.tools.menu_tools import _load_menu, resolve_menu_item

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


def test_exact_name_match_resolves_found():
    match = resolve_menu_item("Kung Pao Chicken", SAMPLE_MENU)

    assert match.status == "found"
    assert match.item["name"] == "Kung Pao Chicken"


def test_case_insensitive_exact_match_resolves_found():
    match = resolve_menu_item("kung pao chicken", SAMPLE_MENU)

    assert match.status == "found"
    assert match.item["name"] == "Kung Pao Chicken"


def test_partial_substring_match_resolves_found_when_unique():
    match = resolve_menu_item("Mapo", SAMPLE_MENU)

    assert match.status == "found"
    assert match.item["name"] == "Mapo Tofu"


def test_minor_typo_resolves_found():
    match = resolve_menu_item("Sprng Rolls", SAMPLE_MENU)

    assert match.status == "found"
    assert match.item["name"] == "Spring Rolls"


def test_not_found_when_nothing_meets_the_cutoff():
    match = resolve_menu_item("Pizza", SAMPLE_MENU)

    assert match.status == "not_found"


def test_tie_when_two_items_score_equally_at_the_top():
    match = resolve_menu_item("Beef Noodle", SAMPLE_MENU)

    assert match.status == "tie"
    assert set(match.candidates) == {"Beef Noodle Soup", "Beef Noodle Bowl"}


def test_real_menu_json_has_at_least_five_well_formed_items():
    menu = _load_menu()

    assert len(menu) >= 5
    for item in menu:
        assert isinstance(item["name"], str) and item["name"]
        assert isinstance(item["price"], (int, float)) and item["price"] > 0
        assert isinstance(item["ingredients"], list) and item["ingredients"]
