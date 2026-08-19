"""Sticker-price cost accounting for Anthropic models, including
prompt-cache write (1.25x input) and read (0.1x input) rates.
"""

# USD price per MILLION tokens, keyed by model-id prefix: (input, output).
# Sonnet 5 carries an intro price through 2026-08-31; we display sticker
# price and do not attempt to model the promotional window here.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus": (5.00, 25.00),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int,
            cache_creation_tokens: int = 0, cache_read_tokens: int = 0) -> float | None:
    """USD cost for a call, or None when `model` matches no known prefix.

    Longest-prefix match: if more than one key in PRICES prefixes `model`,
    the most specific (longest) one wins.

    Cache writes are billed at 1.25x the model's base input rate and cache
    reads at 0.1x -- both fractions of the same input rate, per Anthropic's
    prompt caching pricing.
    """
    match = max((key for key in PRICES if model.startswith(key)), key=len, default=None)
    if match is None:
        return None
    price_in, price_out = PRICES[match]
    return ((input_tokens / 1_000_000) * price_in
            + (output_tokens / 1_000_000) * price_out
            + (cache_creation_tokens / 1_000_000) * price_in * 1.25
            + (cache_read_tokens / 1_000_000) * price_in * 0.1)
