import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchJson } from "./api";
import type {
  DashboardConfig,
  HotkeysCheckResponse,
  HotkeysConfigResponse,
  SubnetOverviewRow,
  TaostatsDivergenceResponse,
  TaostatsOverviewResponse,
} from "./types";
import "./App.css";

function formatPct(v: number | null): string {
  if (v == null) return "—";
  return `${v.toFixed(2)}%`;
}

/** Percent change from previous to current; null if previous baseline is zero. */
function pctFromPrev(prev: number, now: number): number | null {
  if (prev <= 0 && now <= 0) return 0;
  if (prev <= 0) return null;
  return ((now - prev) / prev) * 100;
}

/** Like pctFromPrev but for nullable API fields (missing vs 0). */
function pctDelta(prev: number | null, now: number | null): number | null {
  if (prev === null || now === null) return null;
  return pctFromPrev(prev, now);
}

function formatTaoDay(tau: number | null): string {
  if (tau == null || !Number.isFinite(tau)) return "—";
  const v = Math.max(0, tau);
  return v.toFixed(6);
}

function formatBurnPct(rate: number | null): string {
  if (rate == null || !Number.isFinite(rate)) return "—";
  return `${(rate * 100).toFixed(2)}%`;
}

function formatDeltaPct(pct: number): string {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

type HotkeyUiRow = {
  name: string;
  netuid: number;
  hotkey: string;
  /** null = not checked yet */
  registered: boolean | null;
  uid: number | null;
  error: string | null;
  refreshing: boolean;
};

type MainTab = "taostats" | "hotkeys";

export default function App() {
  const [mainTab, setMainTab] = useState<MainTab>("taostats");
  const [config, setConfig] = useState<DashboardConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  const [taostatsLoading, setTaostatsLoading] = useState(false);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [taostatsStatus, setTaostatsStatus] = useState("");
  const [taostatsWarn, setTaostatsWarn] = useState("");
  const [taostatsWarnIsError, setTaostatsWarnIsError] = useState(false);
  const [divergence, setDivergence] = useState<TaostatsDivergenceResponse | null>(null);

  const [overviewData, setOverviewData] = useState<TaostatsOverviewResponse | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [overviewDeltas, setOverviewDeltas] = useState<
    Record<number, { emission: number | null; burn: number | null; reg: number | null }>
  >({});
  const prevOverviewRef = useRef<Record<
    number,
    { emission: number | null; burn: number | null; reg: number | null }
  > | null>(null);

  const [hotkeyNetwork, setHotkeyNetwork] = useState<string | null>(null);
  const [hotkeyRows, setHotkeyRows] = useState<HotkeyUiRow[]>([]);
  const [hotkeysListError, setHotkeysListError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const c = await fetchJson<DashboardConfig>("/api/config");
        if (!cancelled) {
          setConfig(c);
          setConfigError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setConfig(null);
          setConfigError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const h = await fetchJson<HotkeysConfigResponse>("/api/hotkeys/config");
        if (!cancelled) {
          setHotkeyNetwork(h.network);
          setHotkeyRows(
            h.hotkeys.map((x) => ({
              name: x.name,
              netuid: x.netuid,
              hotkey: x.hotkey,
              registered: null,
              uid: null,
              error: null,
              refreshing: false,
            })),
          );
          setHotkeysListError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setHotkeyRows([]);
          setHotkeysListError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const applyOverviewData = useCallback((data: TaostatsOverviewResponse) => {
    const prev = prevOverviewRef.current;
    const deltas: Record<number, { emission: number | null; burn: number | null; reg: number | null }> =
      {};
    if (prev) {
      for (const r of data.subnets) {
        const p = prev[r.netuid];
        if (!p) continue;
        deltas[r.netuid] = {
          emission: pctDelta(p.emission, r.emission_tau_per_day),
          burn: pctDelta(p.burn, r.incentive_burn_rate),
          reg: pctDelta(p.reg, r.neuron_registration_cost_tao),
        };
      }
    }
    setOverviewDeltas(deltas);
    prevOverviewRef.current = Object.fromEntries(
      data.subnets.map((s) => [
        s.netuid,
        {
          emission: s.emission_tau_per_day,
          burn: s.incentive_burn_rate,
          reg: s.neuron_registration_cost_tao,
        },
      ]),
    );
    setOverviewData(data);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setOverviewLoading(true);
      setOverviewError(null);
      try {
        const ov = await fetchJson<TaostatsOverviewResponse>("/api/taostats/overview");
        if (cancelled) return;
        applyOverviewData(ov);
      } catch (e) {
        if (!cancelled) {
          setOverviewError(e instanceof Error ? e.message : String(e));
          setOverviewData(null);
        }
      } finally {
        if (!cancelled) setOverviewLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [applyOverviewData]);

  const refreshTaostats = useCallback(async () => {
    setTaostatsLoading(true);
    setOverviewLoading(true);
    setTaostatsStatus("Loading…");
    setTaostatsWarn("");
    setTaostatsWarnIsError(false);
    setDivergence(null);
    setOverviewError(null);
    try {
      const [ov, j] = await Promise.all([
        fetchJson<TaostatsOverviewResponse>("/api/taostats/overview"),
        fetchJson<TaostatsDivergenceResponse>("/api/taostats/divergence"),
      ]);
      applyOverviewData(ov);
      setDivergence(j);
      if (j.warning) {
        setTaostatsWarn(j.warning);
        setTaostatsWarnIsError(true);
      } else {
        const hrs = j.lookback_sec != null ? Math.round(j.lookback_sec / 3600) : 24;
        setTaostatsWarn(
          j.baseline_time
            ? `Baseline snapshot ~${hrs}h lookback (unix ${j.baseline_time}).`
            : "",
        );
        setTaostatsWarnIsError(false);
      }
      setTaostatsStatus(`${j.subnet_count} subnets · snapshot ${j.snapshot_time ?? "—"}`);
    } catch (e) {
      setTaostatsStatus("");
      setTaostatsWarn(e instanceof Error ? e.message : String(e));
      setTaostatsWarnIsError(true);
      setOverviewError(e instanceof Error ? e.message : String(e));
    } finally {
      setTaostatsLoading(false);
      setOverviewLoading(false);
    }
  }, [applyOverviewData]);

  const refreshOneHotkey = useCallback(async (netuid: number, ss58: string) => {
    if (!ss58) return;
    setHotkeyRows((prev) =>
      prev.map((r) =>
        r.netuid === netuid && r.hotkey === ss58 ? { ...r, refreshing: true, error: null } : r,
      ),
    );
    try {
      const j = await fetchJson<HotkeysCheckResponse>("/api/hotkeys/check", {
        method: "POST",
        body: JSON.stringify({ netuid, ss58 }),
      });
      const res = j.results[0];
      if (!res) throw new Error("empty result");
      setHotkeyRows((prev) =>
        prev.map((r) =>
          r.netuid === netuid && r.hotkey === ss58
            ? {
                ...r,
                name: res.name || r.name,
                registered: res.registered,
                uid: res.uid ?? null,
                error: res.error,
                refreshing: false,
              }
            : r,
        ),
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setHotkeyRows((prev) =>
        prev.map((r) =>
          r.netuid === netuid && r.hotkey === ss58
            ? { ...r, error: msg, refreshing: false }
            : r,
        ),
      );
    }
  }, []);

  const th = config?.min_divergence_pct ?? 2;
  const lookbackH = config ? Math.round(config.lookback_sec / 3600) : 24;

  return (
    <>
      <h1>Bittensor tools dashboard</h1>

      {configError ? (
        <p className="sub warn-text">
          Could not load <code>/api/config</code>: {configError}. Is the Python backend running
          (e.g. uvicorn on port 8765) and is the Vite proxy configured?
        </p>
      ) : !config ? (
        <p className="sub">Loading settings…</p>
      ) : null}

      <div className="tabs">
        <div className="tabs-list" role="tablist" aria-label="Dashboard views">
          <button
            type="button"
            role="tab"
            id="tab-taostats"
            className={`tab-btn ${mainTab === "taostats" ? "active" : ""}`}
            aria-selected={mainTab === "taostats"}
            aria-controls="panel-taostats"
            tabIndex={mainTab === "taostats" ? 0 : -1}
            onClick={() => setMainTab("taostats")}
          >
            Taostats monitor
          </button>
          <button
            type="button"
            role="tab"
            id="tab-hotkeys"
            className={`tab-btn ${mainTab === "hotkeys" ? "active" : ""}`}
            aria-selected={mainTab === "hotkeys"}
            aria-controls="panel-hotkeys"
            tabIndex={mainTab === "hotkeys" ? 0 : -1}
            onClick={() => setMainTab("hotkeys")}
          >
            Registered hotkeys
          </button>
        </div>

        <div
          id="panel-taostats"
          role="tabpanel"
          aria-labelledby="tab-taostats"
          hidden={mainTab !== "taostats"}
          className="tab-panel"
        >
          {config ? (
            <>
              <p className="sub">
                <strong>All subnets</strong>: <strong>alpha price</strong> (τ/α, pool API),{" "}
                <strong>emission/day (τ)</strong> = Taostats subnet/latest <code>projected_emission</code> (τ/block,{" "}
                share of TAO into the subnet) × blocks/day (default {overviewData?.blocks_per_day ?? 7200},{" "}
                <code>TAOSTATS_BLOCKS_PER_DAY</code>), always ≥ 0.                 <strong>Reg cost (τ)</strong> = <code>neuron_registration_cost</code> from subnet/latest.{" "}
                <strong>Incentive burn</strong> = <code>incentive_burn</code> (%, chain param). Blue % =
                change vs your last refresh (numeric columns).
              </p>
              <p className="sub">
                <strong>24h divergence table</strong> (below): subnets where daily % moves in emission vs
                burn differ by ≥ <strong>{th}</strong> pp (~<strong>{lookbackH}h</strong> baseline,{" "}
                <code>TAOSTATS_MIN_DIVERGENCE_PCT</code>).
              </p>
            </>
          ) : null}
          <h2>Taostats monitor</h2>
          <div className="row">
            <button
              type="button"
              disabled={taostatsLoading || overviewLoading}
              onClick={refreshTaostats}
            >
              Refresh Taostats
            </button>
            <span className="msg">
              {overviewLoading && !taostatsLoading ? "Updating subnet table… " : ""}
              {taostatsStatus}
            </span>
          </div>
          <SubnetOverviewTable
            loading={overviewLoading}
            error={overviewError}
            data={overviewData}
            deltas={overviewDeltas}
          />
          <h3 className="subsection-title">24h emission vs burn divergence</h3>
          <p className={taostatsWarnIsError ? "msg warn" : "msg"}>{taostatsWarn}</p>
          <DivergenceTable data={divergence} />
          {config ? (
            <p className="msg footer-hint">
              Snapshot file: <code>{config.snapshot_path}</code> · <code>TAOSTATS_API_KEY</code> in{" "}
              <code>.env</code> ·{" "}
              <a href="/api/config" target="_blank" rel="noopener noreferrer">
                JSON config
              </a>
            </p>
          ) : null}
        </div>

        <div
          id="panel-hotkeys"
          role="tabpanel"
          aria-labelledby="tab-hotkeys"
          hidden={mainTab !== "hotkeys"}
          className="tab-panel"
        >
          <p className="msg">
            Configure <code>hotkeys.yaml</code> (or <code>BITTENSOR_TOOLS_HOTKEYS</code> in{" "}
            <code>.env</code>). Optional <code>BITTENSOR_NETWORK</code> overrides the YAML{" "}
            <code>network</code>.
            {hotkeyNetwork ? (
              <>
                {" "}
                Current network: <code>{hotkeyNetwork}</code>.
              </>
            ) : null}
          </p>
          <h2>Registered hotkeys</h2>
          {hotkeysListError ? (
            <p className="msg warn">Could not load hotkeys list: {hotkeysListError}</p>
          ) : null}
          <HotkeysTable rows={hotkeyRows} onRefresh={refreshOneHotkey} />
        </div>
      </div>
    </>
  );
}

function formatAlphaPrice(p: number | null): string {
  if (p == null || !Number.isFinite(p)) return "—";
  return p.toFixed(8);
}

function formatRegCostTau(tau: number | null): string {
  if (tau == null || !Number.isFinite(tau)) return "—";
  return Math.max(0, tau).toFixed(6);
}

type OverviewSortKey = "netuid" | "name" | "alpha_price" | "emission" | "reg" | "burn";

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
      case "netuid":
        return mult * (a.netuid - b.netuid);
      case "name": {
        const c = a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
        if (c !== 0) return mult * c;
        return mult * (a.netuid - b.netuid);
      }
      case "alpha_price":
        return compareNullableNum(a.alpha_price_tao, b.alpha_price_tao, ascending);
      case "emission":
        return compareNullableNum(a.emission_tau_per_day, b.emission_tau_per_day, ascending);
      case "reg":
        return compareNullableNum(a.neuron_registration_cost_tao, b.neuron_registration_cost_tao, ascending);
      case "burn":
        return compareNullableNum(a.incentive_burn_rate, b.incentive_burn_rate, ascending);
      default:
        return 0;
    }
  });
}

function OverviewSortTh({
  label,
  colKey,
  activeKey,
  sortDir,
  onSort,
}: {
  label: string;
  colKey: OverviewSortKey;
  activeKey: OverviewSortKey;
  sortDir: "asc" | "desc";
  onSort: (k: OverviewSortKey) => void;
}) {
  const active = activeKey === colKey;
  const ariaSort = active ? (sortDir === "asc" ? "ascending" : "descending") : "none";
  return (
    <th scope="col" aria-sort={ariaSort}>
      <button type="button" className="th-sort-btn" onClick={() => onSort(colKey)}>
        {label}
        {active ? <span className="sort-ind">{sortDir === "asc" ? " ▲" : " ▼"}</span> : null}
      </button>
    </th>
  );
}

function SubnetOverviewTable({
  loading,
  error,
  data,
  deltas,
}: {
  loading: boolean;
  error: string | null;
  data: TaostatsOverviewResponse | null;
  deltas: Record<number, { emission: number | null; burn: number | null; reg: number | null }>;
}) {
  const [sortKey, setSortKey] = useState<OverviewSortKey>("netuid");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const toggleSort = (k: OverviewSortKey) => {
    if (sortKey === k) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(k);
      setSortDir("asc");
    }
  };

  const sortedSubnets = useMemo(() => {
    if (!data?.subnets.length) return [];
    return sortSubnetRows(data.subnets, sortKey, sortDir);
  }, [data?.subnets, sortKey, sortDir]);

  if (error && !data) {
    return <p className="msg warn">Subnet table: {error}</p>;
  }
  if (loading && !data) {
    return <p className="msg">Loading subnets…</p>;
  }
  if (!data?.subnets.length) {
    return <p className="msg">{loading ? "Loading subnets…" : "No subnets returned."}</p>;
  }
  return (
    <>
      {data.pool_warning ? <p className="msg warn">{data.pool_warning}</p> : null}
      {error ? <p className="msg warn">Last refresh issue: {error}</p> : null}
      <p className="msg footer-hint">
        Click a column header to sort. Blue <span className="delta-pct inline-delta">(+0.00%)</span> = change
        vs previous refresh for that value.
      </p>
      <div className="table-scroll">
        <table className="subnet-overview-table">
          <thead>
            <tr>
              <OverviewSortTh
                label="netuid"
                colKey="netuid"
                activeKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <OverviewSortTh
                label="Name"
                colKey="name"
                activeKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <OverviewSortTh
                label="Alpha price (τ/α)"
                colKey="alpha_price"
                activeKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <OverviewSortTh
                label="Emission/day (τ)"
                colKey="emission"
                activeKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <OverviewSortTh
                label="Reg cost (τ)"
                colKey="reg"
                activeKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <OverviewSortTh
                label="Incentive burn"
                colKey="burn"
                activeKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
            </tr>
          </thead>
          <tbody>
            {sortedSubnets.map((r) => {
              const d = deltas[r.netuid];
              return (
                <tr key={r.netuid}>
                  <td>
                    <a
                      href={`https://taostats.io/subnets/${r.netuid}`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {r.netuid}
                    </a>
                  </td>
                  <td className="subnet-name-cell">{r.name}</td>
                  <td>{formatAlphaPrice(r.alpha_price_tao)}</td>
                  <td>
                    <span>{formatTaoDay(r.emission_tau_per_day)}</span>
                    {d?.emission != null ? (
                      <span className="delta-pct"> {formatDeltaPct(d.emission)}</span>
                    ) : null}
                  </td>
                  <td>
                    <span>{formatRegCostTau(r.neuron_registration_cost_tao)}</span>
                    {d?.reg != null ? (
                      <span className="delta-pct"> {formatDeltaPct(d.reg)}</span>
                    ) : null}
                  </td>
                  <td>
                    <span>{formatBurnPct(r.incentive_burn_rate)}</span>
                    {d?.burn != null ? (
                      <span className="delta-pct"> {formatDeltaPct(d.burn)}</span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function DivergenceTable({ data }: { data: TaostatsDivergenceResponse | null }) {
  if (!data) {
    return (
      <p className="msg">
        Press <strong>Refresh Taostats</strong> to load this table and append a snapshot for the ~24h
        baseline.
      </p>
    );
  }
  const rows = data.divergences ?? [];
  const th = data.min_divergence_pct ?? 2;
  if (!rows.length) {
    return (
      <p className="msg">
        No subnets over {th}% divergence threshold (or not enough history yet).
      </p>
    );
  }
  return (
    <table>
      <thead>
        <tr>
          <th>netuid</th>
          <th>|Δ emission% − Δ burn%|</th>
          <th>Δ emission / day</th>
          <th>Δ burn / day</th>
          <th>emission now → was</th>
          <th>burn now → was</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((x) => (
          <tr key={x.netuid}>
            <td>
              <a
                href={`https://taostats.io/subnets/${x.netuid}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                {x.netuid}
              </a>
            </td>
            <td>
              <strong>{x.divergence_pct_points.toFixed(2)}</strong>
            </td>
            <td>{formatPct(x.emission_pct_per_day)}</td>
            <td>{formatPct(x.burn_pct_per_day)}</td>
            <td>
              {x.emission_now} → {x.emission_then ?? "—"}
            </td>
            <td>
              {x.burn_now} → {x.burn_then ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HotkeysTable({
  rows,
  onRefresh,
}: {
  rows: HotkeyUiRow[];
  onRefresh: (netuid: number, ss58: string) => void;
}) {
  if (!rows.length) {
    return <p className="msg">No hotkeys in config (empty <code>hotkeys.yaml</code>).</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>netuid</th>
          <th>Status</th>
          <th>uid</th>
          <th>Hotkey</th>
          <th className="actions"> </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.netuid}:${r.hotkey}`}>
            <td>{r.name}</td>
            <td>{r.netuid}</td>
            <td>
              {r.registered === null ? (
                <span className="msg">—</span>
              ) : (
                <span className={`badge ${r.registered ? "ok" : "bad"}`}>
                  {r.registered ? "registered" : "not registered"}
                </span>
              )}
              {r.error ? <span className="msg warn inline-warn"> {r.error}</span> : null}
            </td>
            <td>{r.uid != null ? r.uid : "—"}</td>
            <td>
              <code className="hk">{r.hotkey || "—"}</code>
            </td>
            <td className="actions">
              <button
                type="button"
                className="btn-sm"
                disabled={r.refreshing || !r.hotkey}
                onClick={() => onRefresh(r.netuid, r.hotkey)}
              >
                {r.refreshing ? "…" : "Refresh"}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
