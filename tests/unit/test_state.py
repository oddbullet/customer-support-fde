from customer_support_fde import state


# initial_state() starts a conversation with no tool-call limit breach recorded. (happy)
def test_initial_state_has_no_tool_limit_breach(monkeypatch):
    monkeypatch.setattr(state.db, "load_menu", lambda: [])

    assert state.initial_state("hi")["tool_limit_reached"] is None
