from prcrew.pricing import cost_usd


def test_known_model_computes_cost_from_per_million_prices():
    # claude-sonnet-5: $3/M in, $15/M out
    cost = cost_usd("claude-sonnet-5-20260101", 1_000_000, 1_000_000)
    assert cost == 18.00

def test_unknown_model_returns_none():
    assert cost_usd("gpt-4o", 1_000_000, 1_000_000) is None

def test_prefix_match_on_full_model_id():
    cost = cost_usd("claude-haiku-4-5-20251001", 1_000_000, 0)
    assert cost == 1.00

def test_zero_tokens_costs_zero_for_known_model():
    assert cost_usd("claude-opus", 0, 0) == 0.0
