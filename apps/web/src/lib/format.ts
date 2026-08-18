import type { Usage } from "./types";

/** Compact "1.2k tok" formatting for a footer line; null when usage is absent. */
export function formatTokens(usage?: Usage): string | null {
  if (!usage) return null;
  const total = usage.input_tokens + usage.output_tokens;
  const compact = total >= 1000 ? `${(total / 1000).toFixed(1)}k` : `${total}`;
  return `${compact} tok`;
}

/** "$0.0011"-style cost formatting to 3-4 significant decimals. */
export function formatCost(costUsd: number): string {
  if (costUsd === 0) return "$0";
  const decimals = costUsd >= 1 ? 2 : costUsd >= 0.01 ? 3 : 4;
  return `$${costUsd.toFixed(decimals)}`;
}
