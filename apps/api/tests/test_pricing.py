import pytest

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

def test_cache_tokens_price_writes_at_1_25x_and_reads_at_0_1x_input_rate():
    # claude-haiku-4-5: $1.00/M in -> writes $1.25/M, reads $0.10/M
    cost = cost_usd("claude-haiku-4-5-20251001", 0, 0,
                    cache_creation_tokens=1_000_000, cache_read_tokens=1_000_000)
    assert cost == pytest.approx(1.25 + 0.10)
