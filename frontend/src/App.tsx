import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchJson } from "./api";
import { AlarmsModal } from "./components/alarms/AlarmsPanel";
import { FavoriteNotificationsSettings, FavoriteSubnetsList } from "./components/favorites/Favorites";
import { DashboardHero, type ThemeMode } from "./components/layout/DashboardHero";
import { TabsShell } from "./components/layout/Tabs";
import { MinerRewardsModal } from "./components/miners/MinerRewardsModal";
import { DivergenceTable, HIGH_DIVERGENCE_HIGHLIGHT_PP, SubnetOverviewTable, type OverviewDeltaRow } from "./components/taostats/TaostatsTables";
import { actualRewardTauPerDay, parseFavoritesResponse, pctDelta } from "./utils/dashboard";
import { formatUnixSeconds } from "./utils/format";
import type {
  DashboardConfig,
  FavoriteAlerts,
  FavoritesResponse,
  TaoDailyNewsResponse,
  TaoMarketCapSubnetMinersResponse,
  TaostatsDivergenceResponse,
  TaostatsOverviewResponse,
} from "./types";
import "./App.css";

type MainTab = "taostats" | "favorites";

/**
 * Legacy localStorage key — favorites are now persisted on the backend via
 * /api/favorites so the 10-min Telegram digest can read them. This key is kept
 * only so existing browser-side favorites get migrated once on first load.
 */
const LEGACY_FAVORITES_STORAGE_KEY = "bittensor-tools.favorite-subnets";
const THEME_STORAGE_KEY = "bittensor-tools.theme-mode";

function readInitialTheme(): ThemeMode {
  if (typeof window === "undefined") return "day";
  return window.localStorage.getItem(THEME_STORAGE_KEY) === "dark" ? "dark" : "day";
}

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
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => readInitialTheme());
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
  const [minerModalNetuid, setMinerModalNetuid] = useState<number | null>(null);
  const [minerModalData, setMinerModalData] = useState<TaoMarketCapSubnetMinersResponse | null>(null);
  const [minerModalLoading, setMinerModalLoading] = useState(false);
  const [minerModalError, setMinerModalError] = useState<string | null>(null);

  const [alarmNews, setAlarmNews] = useState<TaoDailyNewsResponse | null>(null);
  const [alarmNewsLoading, setAlarmNewsLoading] = useState(true);
  const [alarmNewsError, setAlarmNewsError] = useState<string | null>(null);
  const [alarmModalOpen, setAlarmModalOpen] = useState(true);

  const [favorites, setFavorites] = useState<Set<number>>(() => new Set());
  const [favoriteAlerts, setFavoriteAlerts] = useState<Record<number, FavoriteAlerts>>({});
  const [favoriteGithub, setFavoriteGithub] = useState<Record<number, string | null>>({});
  const [favoritesError, setFavoritesError] = useState<string | null>(null);
  const favoritesRef = useRef<Set<number>>(new Set());
  /** When true, a late initial GET /api/favorites must not overwrite user toggles. */
  const skipFavoritesHydrationRef = useRef(false);
  const favoritesTogglingRef = useRef<Set<number>>(new Set());
  const [favoritesToggling, setFavoritesToggling] = useState<Set<number>>(() => new Set());

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
    window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);
  }, [themeMode]);

  const applyFavorites = useCallback((ids: number[]) => {
    const next = new Set(ids);
    favoritesRef.current = next;
    setFavorites(next);
  }, []);

  const applyFavoritesConfig = useCallback(
    (resp: FavoritesResponse) => {
      const { ids, alerts, github } = parseFavoritesResponse(resp);
      applyFavorites(ids);
      setFavoriteAlerts(alerts);
      setFavoriteGithub(github);
    },
    [applyFavorites],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetchJson<FavoritesResponse>("/api/favorites");
        if (cancelled) return;
        let parsed = parseFavoritesResponse(resp);
        const legacy = readLegacyFavorites();
        if (parsed.ids.length === 0 && legacy.length > 0) {
          try {
            const migrated = await fetchJson<FavoritesResponse>("/api/favorites", {
              method: "POST",
              body: JSON.stringify({ favorites: legacy }),
            });
            parsed = parseFavoritesResponse(migrated);
          } catch {
            /* migration is best-effort — fall back to whatever the server returned. */
          }
        }
        if (legacy.length > 0) clearLegacyFavorites();
        if (!cancelled && !skipFavoritesHydrationRef.current) {
          applyFavorites(parsed.ids);
          setFavoriteAlerts(parsed.alerts);
          setFavoriteGithub(parsed.github);
          setFavoritesError(null);
        }
      } catch (e) {
        if (!cancelled) setFavoritesError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [applyFavorites]);

  const toggleFavorite = useCallback(
    async (netuid: number) => {
      const nu = Number(netuid);
      if (!Number.isInteger(nu) || nu < 0) return;
      if (favoritesTogglingRef.current.has(nu)) return;

      skipFavoritesHydrationRef.current = true;
      favoritesTogglingRef.current.add(nu);
      setFavoritesToggling((prev) => new Set(prev).add(nu));

      const wasFav = favoritesRef.current.has(nu);
      const optimistic = new Set(favoritesRef.current);
      if (wasFav) optimistic.delete(nu);
      else optimistic.add(nu);
      favoritesRef.current = optimistic;
      setFavorites(optimistic);

      try {
        const resp = await fetchJson<FavoritesResponse>(
          wasFav ? "/api/favorites/remove" : "/api/favorites/add",
          {
            method: "POST",
            body: JSON.stringify({ netuid: nu }),
          },
        );
        applyFavoritesConfig(resp);
        if (wasFav) {
          setFavoriteAlerts((prev) => {
            const next = { ...prev };
            delete next[nu];
            return next;
          });
        }
        setFavoritesError(null);
      } catch (e) {
        const reverted = new Set(favoritesRef.current);
        if (wasFav) reverted.add(nu);
        else reverted.delete(nu);
        favoritesRef.current = reverted;
        setFavorites(reverted);
        setFavoritesError(e instanceof Error ? e.message : String(e));
      } finally {
        favoritesTogglingRef.current.delete(nu);
        setFavoritesToggling((prev) => {
          const next = new Set(prev);
          next.delete(nu);
          return next;
        });
      }
    },
    [applyFavoritesConfig],
  );

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
    setAlarmNewsLoading(true);
    (async () => {
      try {
        const news = await fetchJson<TaoDailyNewsResponse>("/api/alarms/news");
        if (!cancelled) {
          setAlarmNews(news);
          setAlarmNewsError(null);
          if (news.items.length > 0) setAlarmModalOpen(true);
        }
      } catch (e) {
        if (!cancelled) {
          setAlarmNews(null);
          setAlarmNewsError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!cancelled) setAlarmNewsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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
      const j = await fetchJson<TaostatsDivergenceResponse>("/api/taostats/divergence");
      const ov = await fetchJson<TaostatsOverviewResponse>("/api/taostats/overview");
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

  const openMinerRewards = useCallback(async (netuid: number) => {
    setMinerModalNetuid(netuid);
    setMinerModalData(null);
    setMinerModalError(null);
    setMinerModalLoading(true);
    try {
      const data = await fetchJson<TaoMarketCapSubnetMinersResponse>(
        `/api/taomarketcap/subnets/${netuid}/miners`,
      );
      setMinerModalData(data);
    } catch (e) {
      setMinerModalError(e instanceof Error ? e.message : String(e));
    } finally {
      setMinerModalLoading(false);
    }
  }, []);

  const closeMinerRewards = useCallback(() => {
    setMinerModalNetuid(null);
    setMinerModalData(null);
    setMinerModalError(null);
    setMinerModalLoading(false);
  }, []);

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

  const th = config?.min_divergence_pct ?? 2;
  const lookbackH = config ? Math.round(config.lookback_sec / 3600) : 24;

  return (
    <>
      <DashboardHero
        themeMode={themeMode}
        onToggleTheme={() => setThemeMode((mode) => (mode === "day" ? "dark" : "day"))}
        subnetsCount={overviewData?.subnets.length ?? "—"}
        favoritesCount={favorites.size}
      />

      {configError ? (
        <p className="sub warn-text">
          Could not load <code>/api/config</code>: {configError}. Is the Python backend running
          (e.g. uvicorn on port 8765) and is the Vite proxy configured?
        </p>
      ) : !config ? (
        <p className="sub">Loading settings…</p>
      ) : null}

      <TabsShell>
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
          <SubnetOverviewTable
            loading={overviewLoading}
            error={overviewError}
            data={overviewData}
            deltas={overviewDeltas}
            highlightNetuids={highDivergenceNetuids}
            favorites={favorites}
            onToggleFavorite={toggleFavorite}
            favoritesToggling={favoritesToggling}
            onOpenMinerRewards={openMinerRewards}
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
            All favorites in one table. Click a row to expand <strong>alert thresholds</strong> and
            an optional <strong>GitHub repo</strong> (new commits → Discord). Config:{" "}
            <code>{config?.favorites_config_path ?? "favorites.yaml"}</code>.
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
            <FavoriteSubnetsList
              loading={overviewLoading}
              overviewError={overviewError}
              overviewData={overviewData}
              favoriteIds={[...favorites].sort((a, b) => a - b)}
              favoriteAlerts={favoriteAlerts}
              favoriteGithub={favoriteGithub}
              deltas={overviewDeltas}
              highlightNetuids={highDivergenceNetuids}
              onToggleFavorite={toggleFavorite}
              favoritesToggling={favoritesToggling}
              onAlertsSaved={applyFavoritesConfig}
            />
          )}
          <h3 className="subsection-title">Notifications</h3>
          <FavoriteNotificationsSettings favoriteCount={favorites.size} />
        </div>

      </TabsShell>
      {minerModalNetuid != null ? (
        <MinerRewardsModal
          netuid={minerModalNetuid}
          subnetName={
            overviewData?.subnets.find((s) => Number(s.netuid) === minerModalNetuid)?.name ?? null
          }
          data={minerModalData}
          loading={minerModalLoading}
          error={minerModalError}
          onClose={closeMinerRewards}
        />
      ) : null}
      {alarmModalOpen ? (
        <AlarmsModal
          data={alarmNews}
          loading={alarmNewsLoading}
          error={alarmNewsError}
          onClose={() => setAlarmModalOpen(false)}
        />
      ) : null}
    </>
  );
}

