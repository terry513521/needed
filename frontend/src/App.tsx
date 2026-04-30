import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { fetchJson } from "./api";
import type {
  DashboardConfig,
  FavoritesResponse,
  HotkeysCheckResponse,
  HotkeysConfigResponse,
  SubnetOverviewRow,
  TaostatsDivergenceResponse,
  TaostatsOverviewResponse,
  TelegramStatus,
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

/** Backend snapshot/baseline timestamps are Unix seconds. */
function formatUnixSeconds(ts: number | null | undefined): string {
  if (ts == null || !Number.isFinite(ts)) return "—";
  return new Date(ts * 1000).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

function formatAgeAgo(tsSec: number): string {
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

/** Miner-facing τ/day after incentive burn: alpha emission (τ/day) × (1 − burn rate). */
function actualRewardTauPerDay(alphaEmissionTauPerDay: number | null, burn: number | null): number | null {
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

function formatDeltaPct(pct: number): string {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

/** Highlight rows when |Δ emission% − Δ burn%| is strictly above this (percentage points). */
const HIGH_DIVERGENCE_HIGHLIGHT_PP = 2;

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

function hotkeysConfigToUiRows(h: HotkeysConfigResponse): HotkeyUiRow[] {
  return h.hotkeys.map((x) => ({
    name: x.name,
    netuid: x.netuid,
    hotkey: x.hotkey,
    registered: null,
    uid: null,
    error: null,
    refreshing: false,
  }));
}

type MainTab = "taostats" | "favorites" | "hotkeys";

type OverviewDeltaRow = {
  emission: number | null;
  alphaEmission: number | null;
  burn: number | null;
  reg: number | null;
  actualReward: number | null;
};

/**
 * Legacy localStorage key — favorites are now persisted on the backend via
 * /api/favorites so the 10-min Telegram digest can read them. This key is kept
 * only so existing browser-side favorites get migrated once on first load.
 */
const LEGACY_FAVORITES_STORAGE_KEY = "bittensor-tools.favorite-subnets";

function readLegacyFavorites(): number[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(LEGACY_FAVORITES_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    const out: number[] = [];
    const seen = new Set<number>();
    for (const v of parsed) {
      const n = typeof v === "number" ? v : Number(v);
      if (!Number.isInteger(n) || n < 0 || seen.has(n)) continue;
      seen.add(n);
      out.push(n);
    }
    return out;
  } catch {
    return [];
  }
}

function clearLegacyFavorites(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(LEGACY_FAVORITES_STORAGE_KEY);
  } catch {
    /* private mode / quota — best-effort. */
  }
}

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
  const [overviewDeltas, setOverviewDeltas] = useState<Record<number, OverviewDeltaRow>>({});
  const prevOverviewRef = useRef<Record<number, OverviewDeltaRow> | null>(null);

  const [hotkeyNetwork, setHotkeyNetwork] = useState<string | null>(null);
  const [hotkeyRows, setHotkeyRows] = useState<HotkeyUiRow[]>([]);
  const [hotkeysListError, setHotkeysListError] = useState<string | null>(null);
  const [hotkeysActionError, setHotkeysActionError] = useState<string | null>(null);

  const [favorites, setFavorites] = useState<Set<number>>(() => new Set());
  const [favoritesError, setFavoritesError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetchJson<FavoritesResponse>("/api/favorites");
        if (cancelled) return;
        let serverList = Array.isArray(resp.favorites) ? resp.favorites : [];
        const legacy = readLegacyFavorites();
        if (serverList.length === 0 && legacy.length > 0) {
          try {
            const migrated = await fetchJson<FavoritesResponse>("/api/favorites", {
              method: "POST",
              body: JSON.stringify({ favorites: legacy }),
            });
            if (Array.isArray(migrated.favorites)) serverList = migrated.favorites;
          } catch {
            /* migration is best-effort — fall back to whatever the server returned. */
          }
        }
        if (legacy.length > 0) clearLegacyFavorites();
        if (!cancelled) {
          setFavorites(new Set(serverList));
          setFavoritesError(null);
        }
      } catch (e) {
        if (!cancelled) setFavoritesError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleFavorite = useCallback(async (netuid: number) => {
    let wasFav = false;
    setFavorites((prev) => {
      wasFav = prev.has(netuid);
      const next = new Set(prev);
      if (wasFav) next.delete(netuid);
      else next.add(netuid);
      return next;
    });
    try {
      const resp = await fetchJson<FavoritesResponse>(
        wasFav ? "/api/favorites/remove" : "/api/favorites/add",
        {
          method: "POST",
          body: JSON.stringify({ netuid }),
        },
      );
      if (Array.isArray(resp.favorites)) {
        setFavorites(new Set(resp.favorites));
      }
      setFavoritesError(null);
    } catch (e) {
      setFavorites((prev) => {
        const next = new Set(prev);
        if (wasFav) next.add(netuid);
        else next.delete(netuid);
        return next;
      });
      setFavoritesError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const favoriteOverviewData = useMemo<TaostatsOverviewResponse | null>(() => {
    if (!overviewData) return null;
    return {
      ...overviewData,
      subnets: overviewData.subnets.filter((s) => favorites.has(s.netuid)),
    };
  }, [overviewData, favorites]);

  const applyHotkeysConfig = useCallback((h: HotkeysConfigResponse) => {
    setHotkeyNetwork(h.network);
    setHotkeyRows(hotkeysConfigToUiRows(h));
    setHotkeysListError(null);
    setHotkeysActionError(null);
  }, []);

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
        if (!cancelled) applyHotkeysConfig(h);
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
  }, [applyHotkeysConfig]);

  const applyOverviewData = useCallback((data: TaostatsOverviewResponse) => {
    const prev = prevOverviewRef.current;
    const deltas: Record<number, OverviewDeltaRow> = {};
    if (prev) {
      for (const r of data.subnets) {
        const p = prev[r.netuid];
        if (!p) continue;
        const nowAr = actualRewardTauPerDay(r.alpha_emission_tau_per_day ?? null, r.incentive_burn_rate);
        deltas[r.netuid] = {
          emission: pctDelta(p.emission, r.emission_tau_per_day),
          alphaEmission: pctDelta(p.alphaEmission, r.alpha_emission_tau_per_day ?? null),
          burn: pctDelta(p.burn, r.incentive_burn_rate),
          reg: pctDelta(p.reg, r.neuron_registration_cost_tao),
          actualReward: pctDelta(p.actualReward, nowAr),
        };
      }
    }
    setOverviewDeltas(deltas);
    prevOverviewRef.current = Object.fromEntries(
      data.subnets.map((s) => [
        s.netuid,
        {
          emission: s.emission_tau_per_day,
          alphaEmission: s.alpha_emission_tau_per_day ?? null,
          burn: s.incentive_burn_rate,
          reg: s.neuron_registration_cost_tao,
          actualReward: actualRewardTauPerDay(s.alpha_emission_tau_per_day ?? null, s.incentive_burn_rate),
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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const snap = await fetchJson<TaostatsDivergenceResponse>("/api/taostats/divergence/snapshot");
        if (cancelled) return;
        setDivergence(snap);
        if (snap.warning) {
          setTaostatsWarn(snap.warning);
          setTaostatsWarnIsError(false);
        }
        if (snap.from_snapshot_file && snap.snapshot_time != null) {
          setTaostatsStatus(
            (prev) =>
              prev ||
              `${snap.subnet_count} subnets · snapshot ${formatUnixSeconds(snap.snapshot_time)}`,
          );
        }
      } catch {
        /* Snapshot file missing or server error — live refresh still works. */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshTaostats = useCallback(async () => {
    setTaostatsLoading(true);
    setOverviewLoading(true);
    setTaostatsStatus("Loading…");
    setTaostatsWarn("");
    setTaostatsWarnIsError(false);
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
            ? `Baseline snapshot ~${hrs}h lookback (${formatUnixSeconds(j.baseline_time)}).`
            : "",
        );
        setTaostatsWarnIsError(false);
      }
      const snapLabel =
        j.snapshot_time != null ? formatUnixSeconds(j.snapshot_time) : "—";
      setTaostatsStatus(`${j.subnet_count} subnets · snapshot ${snapLabel}`);
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

  const highDivergenceNetuids = useMemo(() => {
    const set = new Set<number>();
    if (!divergence?.divergences?.length) return set;
    for (const r of divergence.divergences) {
      if (r.divergence_pct_points > HIGH_DIVERGENCE_HIGHLIGHT_PP) {
        set.add(r.netuid);
      }
    }
    return set;
  }, [divergence?.divergences]);

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

  const deleteHotkeyRow = useCallback(
    async (netuid: number, ss58: string) => {
      if (!ss58) return;
      if (!window.confirm(`Remove this hotkey from the config file (netuid ${netuid})?`)) return;
      setHotkeysActionError(null);
      try {
        const h = await fetchJson<HotkeysConfigResponse>("/api/hotkeys/remove", {
          method: "POST",
          body: JSON.stringify({ netuid, ss58 }),
        });
        applyHotkeysConfig(h);
      } catch (e) {
        setHotkeysActionError(e instanceof Error ? e.message : String(e));
      }
    },
    [applyHotkeysConfig],
  );

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
            id="tab-favorites"
            className={`tab-btn ${mainTab === "favorites" ? "active" : ""}`}
            aria-selected={mainTab === "favorites"}
            aria-controls="panel-favorites"
            tabIndex={mainTab === "favorites" ? 0 : -1}
            onClick={() => setMainTab("favorites")}
          >
            Favorite subnets
            {favorites.size > 0 ? <span className="tab-count"> ({favorites.size})</span> : null}
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
                <strong>All subnets</strong>: <strong>alpha price</strong> (τ/α, dTAO pool/latest).{" "}
                <strong>Root TAO in (τ/day)</strong> = mainnet TAO into the subnet pool: subnet/latest{" "}
                <code>emission</code> (rao/block ÷ 1e9) × blocks/day (default{" "}
                {overviewData?.blocks_per_day ?? 7200}, <code>TAOSTATS_BLOCKS_PER_DAY</code>).{" "}
                <strong>Alpha emission (τ/day)</strong> = subnet <code>alpha_rewards</code> (α/block in rao, dTAO
                subnet_emission API) ÷ 1e9 × alpha price × blocks/day (value of emitted α in TAO).{" "}
                <strong>Reg cost (τ)</strong> = <code>neuron_registration_cost</code>.{" "}
                <strong>Incentive burn</strong> = <code>incentive_burn</code>.{" "}
                <strong>Actual reward (τ/day)</strong> = alpha emission (τ/day) × (1 − burn rate). Blue % = change vs
                your last refresh (numeric columns).
              </p>
              <p className="sub">
                <strong>24h divergence table</strong> (below): subnets where daily % moves in emission vs
                burn differ by ≥ <strong>{th}</strong> pp (~<strong>{lookbackH}h</strong> baseline,{" "}
                <code>TAOSTATS_MIN_DIVERGENCE_PCT</code>). It loads from your on-disk snapshot when you open
                the page; <strong>Refresh Taostats</strong> fetches live data and appends a new snapshot. Rows
                with divergence <strong>&gt; 2</strong> pp are highlighted here and in the subnet table above.
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
          {divergence?.snapshot_time != null ? (
            <p className="msg snapshot-taken">
              <strong>Snapshot taken</strong>: {formatUnixSeconds(divergence.snapshot_time)}
              <span className="sub"> ({formatAgeAgo(divergence.snapshot_time)})</span>
              {divergence.baseline_time != null ? (
                <>
                  {" "}
                  · <strong>Baseline</strong>: {formatUnixSeconds(divergence.baseline_time)}
                </>
              ) : null}
            </p>
          ) : null}
          <SubnetOverviewTable
            loading={overviewLoading}
            error={overviewError}
            data={overviewData}
            deltas={overviewDeltas}
            highlightNetuids={highDivergenceNetuids}
            favorites={favorites}
            onToggleFavorite={toggleFavorite}
          />
          <h3 className="subsection-title">24h emission vs burn divergence</h3>
          <p className={taostatsWarnIsError ? "msg warn" : "msg"}>{taostatsWarn}</p>
          {divergence?.from_snapshot_file ? (
            <p className="msg footer-hint">
              Loaded from your snapshot file (no Taostats request). Use <strong>Refresh Taostats</strong>{" "}
              for a live pull and to append a new snapshot.
            </p>
          ) : null}
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
          id="panel-favorites"
          role="tabpanel"
          aria-labelledby="tab-favorites"
          hidden={mainTab !== "favorites"}
          className="tab-panel"
        >
          <p className="sub">
            Subnets you starred on the <strong>Taostats monitor</strong> tab. Favorites are
            persisted to <code>{config?.favorites_config_path ?? "favorites.yaml"}</code> on the
            server, so the backend can push a Telegram digest every{" "}
            {Math.round((config?.favorites_notify_interval_sec ?? 600) / 60)} min.
          </p>
          {favoritesError ? (
            <p className="msg warn">Favorites sync error: {favoritesError}</p>
          ) : null}
          <h2>Favorite subnets</h2>
          {favorites.size === 0 ? (
            <p className="msg">
              No favorites yet. Open the <strong>Taostats monitor</strong> tab and click the ☆
              next to any subnet to pin it here.
            </p>
          ) : (
            <SubnetOverviewTable
              loading={overviewLoading}
              error={overviewError}
              data={favoriteOverviewData}
              deltas={overviewDeltas}
              highlightNetuids={highDivergenceNetuids}
              favorites={favorites}
              onToggleFavorite={toggleFavorite}
              emptyMessage="None of your favorite subnets were returned in the latest overview."
            />
          )}
          <h3 className="subsection-title">Telegram notifications</h3>
          <TelegramSettings favoriteCount={favorites.size} />
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
            <code>network</code> for chain checks only (the file on disk keeps its own{" "}
            <code>network</code>).
            {hotkeyNetwork ? (
              <>
                {" "}
                Effective network: <code>{hotkeyNetwork}</code>.
              </>
            ) : null}{" "}
            Add or remove rows below; changes are written to that YAML file.
          </p>
          <h2>Registered hotkeys</h2>
          {hotkeysListError ? (
            <p className="msg warn">Could not load hotkeys list: {hotkeysListError}</p>
          ) : null}
          {hotkeysActionError ? <p className="msg warn">{hotkeysActionError}</p> : null}
          <h3 className="subsection-title">Add hotkey</h3>
          <HotkeysAddForm onSuccess={applyHotkeysConfig} />
          <HotkeysTable rows={hotkeyRows} onRefresh={refreshOneHotkey} onDelete={deleteHotkeyRow} />
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

type OverviewSortKey =
  | "netuid"
  | "name"
  | "alpha_price"
  | "emission"
  | "alpha_emission"
  | "reg"
  | "burn"
  | "actual_reward";

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
      case "alpha_emission":
        return compareNullableNum(
          a.alpha_emission_tau_per_day ?? null,
          b.alpha_emission_tau_per_day ?? null,
          ascending,
        );
      case "reg":
        return compareNullableNum(a.neuron_registration_cost_tao, b.neuron_registration_cost_tao, ascending);
      case "burn":
        return compareNullableNum(a.incentive_burn_rate, b.incentive_burn_rate, ascending);
      case "actual_reward":
        return compareNullableNum(
          actualRewardTauPerDay(a.alpha_emission_tau_per_day ?? null, a.incentive_burn_rate),
          actualRewardTauPerDay(b.alpha_emission_tau_per_day ?? null, b.incentive_burn_rate),
          ascending,
        );
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
  highlightNetuids,
  favorites,
  onToggleFavorite,
  emptyMessage,
}: {
  loading: boolean;
  error: string | null;
  data: TaostatsOverviewResponse | null;
  deltas: Record<number, OverviewDeltaRow>;
  highlightNetuids: Set<number>;
  favorites: Set<number>;
  onToggleFavorite: (netuid: number) => void;
  emptyMessage?: string;
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
    const fallback = emptyMessage ?? "No subnets returned.";
    return <p className="msg">{loading ? "Loading subnets…" : fallback}</p>;
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
              <th scope="col" className="favorite-col" aria-label="Favorite">
                <span aria-hidden="true">★</span>
              </th>
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
                label="Root TAO in (τ/day)"
                colKey="emission"
                activeKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <OverviewSortTh
                label="Alpha emission (τ/day)"
                colKey="alpha_emission"
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
              <OverviewSortTh
                label="Actual reward (τ/day)"
                colKey="actual_reward"
                activeKey={sortKey}
                sortDir={sortDir}
                onSort={toggleSort}
              />
            </tr>
          </thead>
          <tbody>
            {sortedSubnets.map((r) => {
              const d = deltas[r.netuid];
              const rowHi = highlightNetuids.has(r.netuid);
              const isFav = favorites.has(r.netuid);
              return (
                <tr key={r.netuid} className={rowHi ? "row-high-divergence" : undefined}>
                  <td className="favorite-col">
                    <button
                      type="button"
                      className={`fav-btn${isFav ? " is-fav" : ""}`}
                      onClick={() => onToggleFavorite(r.netuid)}
                      aria-pressed={isFav}
                      aria-label={
                        isFav
                          ? `Remove subnet ${r.netuid} from favorites`
                          : `Add subnet ${r.netuid} to favorites`
                      }
                      title={isFav ? "Remove from favorites" : "Add to favorites"}
                    >
                      {isFav ? "★" : "☆"}
                    </button>
                  </td>
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
                    <span>{formatTaoDay(r.alpha_emission_tau_per_day ?? null)}</span>
                    {d?.alphaEmission != null ? (
                      <span className="delta-pct"> {formatDeltaPct(d.alphaEmission)}</span>
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
                  <td>
                    <span>
                      {formatTaoDay(
                        actualRewardTauPerDay(r.alpha_emission_tau_per_day ?? null, r.incentive_burn_rate),
                      )}
                    </span>
                    {d?.actualReward != null ? (
                      <span className="delta-pct"> {formatDeltaPct(d.actualReward)}</span>
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
        Could not load snapshot-based divergence yet. After you save at least one snapshot (Refresh
        Taostats), reopen the page or check the API server.
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
          <tr
            key={x.netuid}
            className={
              x.divergence_pct_points > HIGH_DIVERGENCE_HIGHLIGHT_PP ? "row-high-divergence" : undefined
            }
          >
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
  onDelete,
}: {
  rows: HotkeyUiRow[];
  onRefresh: (netuid: number, ss58: string) => void;
  onDelete: (netuid: number, ss58: string) => void;
}) {
  if (!rows.length) {
    return <p className="msg">No hotkeys in config yet. Add one above or edit the YAML file.</p>;
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
              <span className="action-btns">
                <button
                  type="button"
                  className="btn-sm"
                  disabled={r.refreshing || !r.hotkey}
                  onClick={() => onRefresh(r.netuid, r.hotkey)}
                >
                  {r.refreshing ? "…" : "Refresh"}
                </button>
                <button
                  type="button"
                  className="btn-sm btn-muted"
                  disabled={!r.hotkey}
                  onClick={() => onDelete(r.netuid, r.hotkey)}
                >
                  Remove
                </button>
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HotkeysAddForm({ onSuccess }: { onSuccess: (h: HotkeysConfigResponse) => void }) {
  const [name, setName] = useState("");
  const [netuid, setNetuid] = useState("");
  const [ss58, setSs58] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const nu = Number(netuid);
    if (!Number.isInteger(nu) || nu < 0) {
      setError("netuid must be a non-negative integer.");
      return;
    }
    const key = ss58.trim();
    if (!key) {
      setError("Hotkey (SS58) is required.");
      return;
    }
    setSubmitting(true);
    try {
      const h = await fetchJson<HotkeysConfigResponse>("/api/hotkeys/entry", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), netuid: nu, ss58: key }),
      });
      onSuccess(h);
      setName("");
      setNetuid("");
      setSs58("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="hotkey-add-form" onSubmit={handleSubmit}>
      {error ? <p className="msg warn hotkey-form-error">{error}</p> : null}
      <div className="hotkey-add-fields">
        <label>
          Name <span className="sub">(optional)</span>
          <input
            type="text"
            value={name}
            onChange={(ev) => setName(ev.target.value)}
            placeholder="Label in the table"
            autoComplete="off"
          />
        </label>
        <label>
          netuid
          <input
            type="text"
            inputMode="numeric"
            value={netuid}
            onChange={(ev) => setNetuid(ev.target.value)}
            placeholder="e.g. 1"
            autoComplete="off"
          />
        </label>
        <label className="hotkey-ss58-field">
          Hotkey (SS58)
          <input
            type="text"
            className="hotkey-ss58-input"
            value={ss58}
            onChange={(ev) => setSs58(ev.target.value)}
            placeholder="5…"
            spellCheck={false}
            autoComplete="off"
          />
        </label>
        <button type="submit" disabled={submitting}>
          {submitting ? "Saving…" : "Add to config"}
        </button>
      </div>
    </form>
  );
}

function TelegramSettings({ favoriteCount }: { favoriteCount: number }) {
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testIsError, setTestIsError] = useState(false);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await fetchJson<TelegramStatus>("/api/notifications/telegram/status");
      setStatus(s);
      setStatusError(null);
    } catch (e) {
      setStatus(null);
      setStatusError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const onSendTest = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    setTestIsError(false);
    try {
      await fetchJson<{ ok: boolean }>("/api/notifications/telegram/test", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setTestResult("Test message sent. Check your Telegram chat.");
      setTestIsError(false);
    } catch (e) {
      setTestResult(e instanceof Error ? e.message : String(e));
      setTestIsError(true);
    } finally {
      setTesting(false);
    }
  }, []);

  const intervalMin =
    status?.interval_sec != null ? Math.max(1, Math.round(status.interval_sec / 60)) : null;

  return (
    <div className="telegram-settings">
      {statusError ? (
        <p className="msg warn">Could not load Telegram status: {statusError}</p>
      ) : status == null ? (
        <p className="msg">Checking Telegram configuration…</p>
      ) : status.configured ? (
        <p className="msg">
          <span className="badge ok">configured</span> Backend will push a digest of your{" "}
          {favoriteCount === 1 ? "1 favorite subnet" : `${favoriteCount} favorite subnets`}{" "}
          every {intervalMin ?? "—"} min while at least one favorite is set.
        </p>
      ) : (
        <p className="msg warn">
          <span className="badge bad">not configured</span> Set{" "}
          <code>TELEGRAM_BOT_TOKEN</code> and <code>TELEGRAM_CHAT_ID</code> in <code>.env</code>{" "}
          and restart the dashboard process to enable the 10-min digest.
          {status.has_token && !status.has_chat_id ? " (TELEGRAM_CHAT_ID is missing.)" : null}
          {!status.has_token && status.has_chat_id ? " (TELEGRAM_BOT_TOKEN is missing.)" : null}
        </p>
      )}
      <div className="row">
        <button
          type="button"
          className="btn-sm"
          disabled={testing || !status?.configured}
          onClick={onSendTest}
          title={
            status?.configured
              ? "Send a hello message to the configured Telegram chat"
              : "Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first"
          }
        >
          {testing ? "Sending…" : "Send test message"}
        </button>
        <button type="button" className="btn-sm btn-muted" onClick={refreshStatus}>
          Recheck
        </button>
        {testResult ? (
          <span className={testIsError ? "msg warn" : "msg"}>{testResult}</span>
        ) : null}
      </div>
    </div>
  );
}
