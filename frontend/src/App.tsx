import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "./api";
import type {
  DashboardConfig,
  HotkeyResult,
  TaostatsDivergenceResponse,
} from "./types";
import "./App.css";

function formatPct(v: number | null): string {
  if (v == null) return "—";
  return `${v.toFixed(2)}%`;
}

export default function App() {
  const [config, setConfig] = useState<DashboardConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  const [taostatsLoading, setTaostatsLoading] = useState(false);
  const [taostatsStatus, setTaostatsStatus] = useState("");
  const [taostatsWarn, setTaostatsWarn] = useState("");
  const [taostatsWarnIsError, setTaostatsWarnIsError] = useState(false);
  const [divergence, setDivergence] = useState<TaostatsDivergenceResponse | null>(null);

  const [hotkeysLoading, setHotkeysLoading] = useState(false);
  const [hotkeysStatus, setHotkeysStatus] = useState("");
  const [hotkeys, setHotkeys] = useState<HotkeyResult[] | null>(null);
  const [hotkeysError, setHotkeysError] = useState<string | null>(null);

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

  const refreshTaostats = useCallback(async () => {
    setTaostatsLoading(true);
    setTaostatsStatus("Loading…");
    setTaostatsWarn("");
    setTaostatsWarnIsError(false);
    setDivergence(null);
    try {
      const j = await fetchJson<TaostatsDivergenceResponse>("/api/taostats/divergence");
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
    } finally {
      setTaostatsLoading(false);
    }
  }, []);

  const checkHotkeys = useCallback(async () => {
    setHotkeysLoading(true);
    setHotkeysStatus("Querying chain…");
    setHotkeys(null);
    setHotkeysError(null);
    try {
      const j = await fetchJson<{ results: HotkeyResult[] }>("/api/hotkeys/check", {
        method: "POST",
      });
      setHotkeys(j.results);
      setHotkeysStatus(`${j.results.length} hotkey(s)`);
    } catch (e) {
      setHotkeysStatus("");
      setHotkeysError(e instanceof Error ? e.message : String(e));
    } finally {
      setHotkeysLoading(false);
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
      ) : config ? (
        <p className="sub">
          Taostats: subnets where <strong>daily % change in emission</strong> and{" "}
          <strong>daily % change in registration burn</strong> (
          <code>neuron_registration_cost</code>) differ by at least{" "}
          <strong>{th}</strong> percentage points (<code>TAOSTATS_MIN_DIVERGENCE_PCT</code> in{" "}
          <code>.env</code>). Baseline window ≈ <strong>{lookbackH}h</strong> ± tolerance. Hotkeys:
          one-click chain check via metagraph.
        </p>
      ) : (
        <p className="sub">Loading settings…</p>
      )}

      <section>
        <h2>Taostats monitor</h2>
        <div className="row">
          <button type="button" disabled={taostatsLoading} onClick={refreshTaostats}>
            Refresh Taostats
          </button>
          <span className="msg">{taostatsStatus}</span>
        </div>
        <p className={taostatsWarnIsError ? "msg warn" : "msg"}>{taostatsWarn}</p>
        <DivergenceTable data={divergence} />
      </section>

      <section>
        <h2>Registered hotkeys</h2>
        <p className="msg">
          Configure <code>hotkeys.yaml</code> (or <code>BITTENSOR_TOOLS_HOTKEYS</code> in{" "}
          <code>.env</code>). Optional <code>BITTENSOR_NETWORK</code> overrides the YAML{" "}
          <code>network</code>.
        </p>
        <div className="row">
          <button type="button" disabled={hotkeysLoading} onClick={checkHotkeys}>
            Check hotkeys on chain
          </button>
          <span className="msg">{hotkeysStatus}</span>
        </div>
        <HotkeysTable results={hotkeys} error={hotkeysError} />
      </section>

      {config && (
        <p className="msg">
          Snapshot file: <code>{config.snapshot_path}</code> · <code>TAOSTATS_API_KEY</code> in{" "}
          <code>.env</code> ·{" "}
          <a href="/api/config" target="_blank" rel="noopener noreferrer">
            JSON config
          </a>
        </p>
      )}
    </>
  );
}

function DivergenceTable({ data }: { data: TaostatsDivergenceResponse | null }) {
  if (!data) return null;
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
  results,
  error,
}: {
  results: HotkeyResult[] | null;
  error: string | null;
}) {
  if (error) {
    return <p className="msg warn">Error: {error}</p>;
  }
  if (!results) return null;
  return (
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>netuid</th>
          <th>Status</th>
          <th>uid</th>
          <th>Hotkey</th>
        </tr>
      </thead>
      <tbody>
        {results.map((x, i) => (
          <tr key={`${x.hotkey}-${x.netuid}-${i}`}>
            <td>{x.name}</td>
            <td>{x.netuid}</td>
            <td>
              <span className={`badge ${x.registered ? "ok" : "bad"}`}>
                {x.registered ? "registered" : "not registered"}
              </span>
              {x.error ? <span className="msg warn inline-warn"> {x.error}</span> : null}
            </td>
            <td>{x.uid != null ? x.uid : "—"}</td>
            <td>
              <code className="hk">{x.hotkey}</code>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
