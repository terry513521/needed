import { Fragment, useMemo, useState } from "react";
import type { SubnetOverviewRow, TaostatsDivergenceResponse, TaostatsOverviewResponse } from "../../types";
import { actualRewardTauPerDay } from "../../utils/dashboard";
import { formatAlphaPrice, formatBurnPct, formatDeltaPct, formatPct, formatRegCostTau, formatTaoDay } from "../../utils/format";

export type OverviewDeltaRow = {
  emission: number | null;
  alphaEmission: number | null;
  burn: number | null;
  reg: number | null;
  actualReward: number | null;
};

export const HIGH_DIVERGENCE_HIGHLIGHT_PP = 2;

type OverviewSortKey = "netuid" | "name" | "alpha_price" | "emission" | "alpha_emission" | "reg" | "burn" | "actual_reward";

function compareNullableNum(a: number | null, b: number | null, ascending: boolean): number {
  const dir = ascending ? 1 : -1;
  const aBad = a == null || !Number.isFinite(a);
  const bBad = b == null || !Number.isFinite(b);
  if (aBad && bBad) return 0;
  if (aBad) return 1;
  if (bBad) return -1;
  if (a === b) return 0;
  return dir * (a < b ? -1 : 1);
}

function sortSubnetRows(rows: SubnetOverviewRow[], key: OverviewSortKey, dir: "asc" | "desc"): SubnetOverviewRow[] {
  const ascending = dir === "asc";
  const mult = ascending ? 1 : -1;
  return [...rows].sort((a, b) => {
    switch (key) {
      case "netuid": return mult * (a.netuid - b.netuid);
      case "name": return mult * (a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || a.netuid - b.netuid);
      case "alpha_price": return compareNullableNum(a.alpha_price_tao, b.alpha_price_tao, ascending);
      case "emission": return compareNullableNum(a.emission_tau_per_day, b.emission_tau_per_day, ascending);
      case "alpha_emission": return compareNullableNum(a.alpha_emission_tau_per_day ?? null, b.alpha_emission_tau_per_day ?? null, ascending);
      case "reg": return compareNullableNum(a.neuron_registration_cost_tao, b.neuron_registration_cost_tao, ascending);
      case "burn": return compareNullableNum(a.incentive_burn_rate, b.incentive_burn_rate, ascending);
      case "actual_reward": return compareNullableNum(
        actualRewardTauPerDay(a.alpha_emission_tau_per_day ?? null, a.incentive_burn_rate),
        actualRewardTauPerDay(b.alpha_emission_tau_per_day ?? null, b.incentive_burn_rate),
        ascending,
      );
      default: return 0;
    }
  });
}

function normalizeExternalUrl(url: string | null | undefined): string | null {
  const value = url?.trim();
  if (!value) return null;
  if (/^https?:\/\//i.test(value)) return value;
  return `https://${value}`;
}

function OverviewSortTh({ label, colKey, activeKey, sortDir, onSort }: {
  label: string;
  colKey: OverviewSortKey;
  activeKey: OverviewSortKey;
  sortDir: "asc" | "desc";
  onSort: (k: OverviewSortKey) => void;
}) {
  const active = activeKey === colKey;
  return (
    <th scope="col" aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="th-sort-btn" onClick={() => onSort(colKey)}>
        {label}{active ? <span className="sort-ind">{sortDir === "asc" ? " ▲" : " ▼"}</span> : null}
      </button>
    </th>
  );
}

export function SubnetOverviewTable({ loading, error, data, deltas, highlightNetuids, favorites, onToggleFavorite, favoritesToggling, onOpenMinerRewards, emptyMessage }: {
  loading: boolean;
  error: string | null;
  data: TaostatsOverviewResponse | null;
  deltas: Record<number, OverviewDeltaRow>;
  highlightNetuids: Set<number>;
  favorites: Set<number>;
  onToggleFavorite: (netuid: number) => void;
  favoritesToggling: Set<number>;
  onOpenMinerRewards: (netuid: number) => void;
  emptyMessage?: string;
}) {
  const [sortKey, setSortKey] = useState<OverviewSortKey>("netuid");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [expandedNetuid, setExpandedNetuid] = useState<number | null>(null);
  const toggleSort = (k: OverviewSortKey) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setSortDir("asc"); }
  };
  const rows = useMemo(() => sortSubnetRows(data?.subnets ?? [], sortKey, sortDir), [data?.subnets, sortKey, sortDir]);
  if (error && !data) return <p className="msg warn">Subnet table: {error}</p>;
  if (loading && !data) return <p className="msg">Loading subnets…</p>;
  if (!rows.length) return <p className="msg">{loading ? "Loading subnets…" : emptyMessage ?? "No subnets returned."}</p>;
  const sortProps = { activeKey: sortKey, sortDir, onSort: toggleSort };
  return (
    <>
      {data?.pool_warning ? <p className="msg warn">{data.pool_warning}</p> : null}
      {error ? <p className="msg warn">Last refresh issue: {error}</p> : null}
      <div className="table-scroll">
        <table className="subnet-overview-table">
          <thead><tr>
            <th scope="col" className="favorite-col" aria-label="Favorite"><span aria-hidden="true">★</span></th>
            <OverviewSortTh label="nid" colKey="netuid" {...sortProps} />
            <OverviewSortTh label="Name" colKey="name" {...sortProps} />
            <OverviewSortTh label="α price" colKey="alpha_price" {...sortProps} />
            <OverviewSortTh label="TAO in/day" colKey="emission" {...sortProps} />
            <OverviewSortTh label="α emit/day" colKey="alpha_emission" {...sortProps} />
            <OverviewSortTh label="Reg τ" colKey="reg" {...sortProps} />
            <OverviewSortTh label="Burn" colKey="burn" {...sortProps} />
            <OverviewSortTh label="Reward/day" colKey="actual_reward" {...sortProps} />
            <th scope="col" className="actions">Status</th>
          </tr></thead>
          <tbody>{rows.map((r) => {
            const d = deltas[r.netuid];
            const nu = Number(r.netuid);
            const isFav = favorites.has(nu);
            const isExpanded = expandedNetuid === nu;
            const githubRepoUrl = normalizeExternalUrl(r.github_repo);
            const logoUrl = normalizeExternalUrl(r.logo_url);
            const subnetUrl = normalizeExternalUrl(r.subnet_url);
            const rowClassName = [
              highlightNetuids.has(r.netuid) ? "row-high-divergence" : null,
              "subnet-row-clickable",
              isExpanded ? "subnet-row-expanded" : null,
            ].filter(Boolean).join(" ");
            return (
              <Fragment key={r.netuid}>
              <tr className={rowClassName} onClick={() => setExpandedNetuid((current) => (current === nu ? null : nu))} title="Click to show subnet links">
                <td className="favorite-col"><button type="button" className={`fav-btn${isFav ? " is-fav" : ""}`} disabled={favoritesToggling.has(nu)} onClick={(event) => { event.stopPropagation(); onToggleFavorite(nu); }} aria-pressed={isFav} title={isFav ? "Remove from favorites" : "Add to favorites"}>{isFav ? "★" : "☆"}</button></td>
                <td><a href={`https://taostats.io/subnets/${r.netuid}`} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()}>{r.netuid}</a></td>
                <td className="subnet-name-cell">{r.name}</td>
                <td>{formatAlphaPrice(r.alpha_price_tao)}</td>
                <td><span>{formatTaoDay(r.emission_tau_per_day)}</span>{d?.emission != null ? <span className="delta-pct"> {formatDeltaPct(d.emission)}</span> : null}</td>
                <td><span>{formatTaoDay(r.alpha_emission_tau_per_day ?? null)}</span>{d?.alphaEmission != null ? <span className="delta-pct"> {formatDeltaPct(d.alphaEmission)}</span> : null}</td>
                <td><span>{formatRegCostTau(r.neuron_registration_cost_tao)}</span>{d?.reg != null ? <span className="delta-pct"> {formatDeltaPct(d.reg)}</span> : null}</td>
                <td><span>{formatBurnPct(r.incentive_burn_rate)}</span>{d?.burn != null ? <span className="delta-pct"> {formatDeltaPct(d.burn)}</span> : null}</td>
                <td><span>{formatTaoDay(actualRewardTauPerDay(r.alpha_emission_tau_per_day ?? null, r.incentive_burn_rate))}</span>{d?.actualReward != null ? <span className="delta-pct"> {formatDeltaPct(d.actualReward)}</span> : null}</td>
                <td className="actions"><button type="button" className="btn-sm btn-muted" onClick={(event) => { event.stopPropagation(); onOpenMinerRewards(nu); }}>Status</button></td>
              </tr>
              {isExpanded ? (
                <tr className="subnet-links-row">
                  <td colSpan={10}>
                    <div className="subnet-links-panel" aria-label={`Subnet ${nu} external links`}>
                      <span className="subnet-links-label">Subnet {nu} links</span>
                      {subnetUrl ? (
                        <a className="subnet-link-icon subnet-logo-link" href={subnetUrl} target="_blank" rel="noopener noreferrer">
                          {logoUrl ? (
                            <img
                              className="subnet-link-logo"
                              src={logoUrl}
                              alt={`${r.name} logo`}
                              loading="lazy"
                              onError={(event) => {
                                event.currentTarget.style.display = "none";
                              }}
                            />
                          ) : (
                            <span className="subnet-link-mark" aria-hidden="true">URL</span>
                          )}
                          <span>{r.name}</span>
                        </a>
                      ) : null}
                      {githubRepoUrl ? (
                        <a className="subnet-link-icon" href={githubRepoUrl} target="_blank" rel="noopener noreferrer">
                          <span className="subnet-link-mark" aria-hidden="true">GH</span>
                          <span>GitHub repo</span>
                        </a>
                      ) : null}
                      <a className="subnet-link-icon" href={`https://taomarketcap.com/subnets/${nu}`} target="_blank" rel="noopener noreferrer">
                        <span className="subnet-link-mark" aria-hidden="true">TM</span>
                        <span>TaoMarketCap</span>
                      </a>
                      <a className="subnet-link-icon" href={`https://taostats.io/subnets/${nu}`} target="_blank" rel="noopener noreferrer">
                        <span className="subnet-link-mark" aria-hidden="true">TS</span>
                        <span>Taostats</span>
                      </a>
                    </div>
                  </td>
                </tr>
              ) : null}
              </Fragment>
            );
          })}</tbody>
        </table>
      </div>
    </>
  );
}

export function DivergenceTable({ data }: { data: TaostatsDivergenceResponse | null }) {
  if (!data) return <p className="msg">Could not load snapshot-based divergence yet. After you save at least one snapshot (Refresh Taostats), reopen the page or check the API server.</p>;
  const rows = data.divergences ?? [];
  const th = data.min_divergence_pct ?? 2;
  if (!rows.length) return <p className="msg">No subnets over {th}% divergence threshold (or not enough history yet).</p>;
  return (
    <table><thead><tr><th>nid</th><th>|Δ emission% − Δ burn%|</th><th>Δ emission / day</th><th>Δ burn / day</th><th>emission now → was</th><th>burn now → was</th></tr></thead>
      <tbody>{rows.map((x) => (
        <tr key={x.netuid} className={x.divergence_pct_points > HIGH_DIVERGENCE_HIGHLIGHT_PP ? "row-high-divergence" : undefined}>
          <td><a href={`https://taostats.io/subnets/${x.netuid}`} target="_blank" rel="noopener noreferrer">{x.netuid}</a></td>
          <td><strong>{x.divergence_pct_points.toFixed(2)}</strong></td>
          <td>{formatPct(x.emission_pct_per_day)}</td>
          <td>{formatPct(x.burn_pct_per_day)}</td>
          <td>{x.emission_now} → {x.emission_then ?? "—"}</td>
          <td>{x.burn_now} → {x.burn_then ?? "—"}</td>
        </tr>
      ))}</tbody>
    </table>
  );
}
