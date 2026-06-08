export function formatPct(v: number | null): string {
  if (v == null) return "—";
  return `${v.toFixed(2)}%`;
}

export function formatTaoDay(tau: number | null): string {
  if (tau == null || !Number.isFinite(tau)) return "—";
  const v = Math.max(0, tau);
  return v.toFixed(6);
}

export function formatBurnPct(rate: number | null): string {
  if (rate == null || !Number.isFinite(rate)) return "—";
  return `${(rate * 100).toFixed(2)}%`;
}

/** Backend snapshot/baseline timestamps are Unix seconds. */
export function formatUnixSeconds(ts: number | null | undefined): string {
  if (ts == null || !Number.isFinite(ts)) return "—";
  return new Date(ts * 1000).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

export function formatAgeAgo(tsSec: number): string {
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - tsSec);
  if (diff < 45) return "just now";
  if (diff < 3600) {
    const m = Math.floor(diff / 60);
    return `${m} min ago`;
  }
  if (diff < 86400) {
    const h = Math.floor(diff / 3600);
    const m = Math.floor((diff % 3600) / 60);
    return m > 0 ? `${h}h ${m}m ago` : `${h}h ago`;
  }
  const d = Math.floor(diff / 86400);
  return d === 1 ? "1 day ago" : `${d} days ago`;
}

export function formatDeltaPct(pct: number): string {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

export function formatAlphaPrice(p: number | null): string {
  if (p == null || !Number.isFinite(p)) return "—";
  return p.toFixed(8);
}

export function formatRegCostTau(tau: number | null): string {
  if (tau == null || !Number.isFinite(tau)) return "—";
  return Math.max(0, tau).toFixed(6);
}

export function compactAddress(value: string): string {
  if (!value) return "—";
  if (value.length <= 16) return value;
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

export function formatCompactAmount(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(2)}K`;
  return value.toFixed(2);
}
