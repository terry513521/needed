import type { FavoriteAlerts, FavoriteEntry, FavoritesResponse } from "../types";

/** Percent change from previous to current; null if previous baseline is zero. */
export function pctFromPrev(prev: number, now: number): number | null {
  if (prev <= 0 && now <= 0) return 0;
  if (prev <= 0) return null;
  return ((now - prev) / prev) * 100;
}

/** Like pctFromPrev but for nullable API fields (missing vs 0). */
export function pctDelta(prev: number | null, now: number | null): number | null {
  if (prev === null || now === null) return null;
  return pctFromPrev(prev, now);
}

/** Miner-facing τ/day after incentive burn: alpha emission (τ/day) × (1 − burn rate). */
export function actualRewardTauPerDay(alphaEmissionTauPerDay: number | null, burn: number | null): number | null {
  if (
    alphaEmissionTauPerDay == null ||
    burn == null ||
    !Number.isFinite(alphaEmissionTauPerDay) ||
    !Number.isFinite(burn)
  ) {
    return null;
  }
  return alphaEmissionTauPerDay * (1 - burn) * 0.41;
}

/** Coerce API / YAML values to deduped non-negative integer netuids. */
export function normalizeFavoriteIds(raw: unknown): number[] {
  if (!Array.isArray(raw)) return [];
  const out: number[] = [];
  const seen = new Set<number>();
  for (const v of raw) {
    const n = typeof v === "number" ? v : Number(v);
    if (!Number.isInteger(n) || n < 0 || seen.has(n)) continue;
    seen.add(n);
    out.push(n);
  }
  return out;
}

export function parseFavoritesResponse(resp: FavoritesResponse): {
  ids: number[];
  alerts: Record<number, FavoriteAlerts>;
  github: Record<number, string | null>;
} {
  const raw = resp.favorites;
  if (!Array.isArray(raw)) return { ids: [], alerts: {}, github: {} };
  if (raw.length > 0 && typeof raw[0] === "number") {
    const ids = normalizeFavoriteIds(raw);
    return { ids, alerts: {}, github: {} };
  }
  const ids: number[] = [];
  const alerts: Record<number, FavoriteAlerts> = {};
  const github: Record<number, string | null> = {};
  for (const item of raw as FavoriteEntry[]) {
    if (!item || typeof item !== "object") continue;
    const nu = Number(item.netuid);
    if (!Number.isInteger(nu) || nu < 0) continue;
    ids.push(nu);
    alerts[nu] = item.alerts ?? {};
    github[nu] = item.github_url ?? null;
  }
  return { ids: normalizeFavoriteIds(ids), alerts, github };
}
