import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { fetchJson } from "../../api";
import type { DiscordStatus, FavoriteAlerts, FavoritesResponse, GithubMonitorStatus, NotificationChannelSetting, NotificationSettingsResponse, SubnetOverviewRow, TaostatsOverviewResponse, TelegramStatus } from "../../types";
import { actualRewardTauPerDay } from "../../utils/dashboard";
import { formatAlphaPrice, formatBurnPct, formatDeltaPct, formatRegCostTau, formatTaoDay } from "../../utils/format";
import type { OverviewDeltaRow } from "../taostats/TaostatsTables";

const ALERT_METRIC_FIELDS: { key: keyof FavoriteAlerts; label: string; short: string }[] = [
  { key: "alpha_price_pct", label: "Alpha price (τ/α)", short: "α price" },
  { key: "root_emission_pct", label: "Root TAO in (τ/day)", short: "TAO in" },
  { key: "alpha_emission_pct", label: "Alpha emission (τ/day)", short: "α emit" },
  { key: "burn_pct", label: "Incentive burn", short: "burn" },
  { key: "reg_pct", label: "Reg cost (τ)", short: "reg" },
  { key: "actual_reward_pct", label: "Actual reward (τ/day)", short: "reward" },
];

function CompactMetricCell({ value, delta }: { value: string; delta?: number | null }) {
  return <td className="compact-num"><span className="compact-val">{value}</span>{delta != null ? <span className="delta-pct compact-delta">{formatDeltaPct(delta)}</span> : null}</td>;
}

export function FavoriteSubnetsList({ loading, overviewError, overviewData, favoriteIds, favoriteAlerts, favoriteGithub, deltas, highlightNetuids, onToggleFavorite, favoritesToggling, onAlertsSaved }: {
  loading: boolean;
  overviewError: string | null;
  overviewData: TaostatsOverviewResponse | null;
  favoriteIds: number[];
  favoriteAlerts: Record<number, FavoriteAlerts>;
  favoriteGithub: Record<number, string | null>;
  deltas: Record<number, OverviewDeltaRow>;
  highlightNetuids: Set<number>;
  onToggleFavorite: (netuid: number) => void;
  favoritesToggling: Set<number>;
  onAlertsSaved: (resp: FavoritesResponse) => void;
}) {
  const rowsByNetuid = useMemo(() => {
    const m = new Map<number, SubnetOverviewRow>();
    for (const s of overviewData?.subnets ?? []) m.set(Number(s.netuid), s);
    return m;
  }, [overviewData?.subnets]);
  const [expandedNetuid, setExpandedNetuid] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<number, Record<string, string>>>({});
  const [githubDrafts, setGithubDrafts] = useState<Record<number, string>>({});
  const [savingNetuid, setSavingNetuid] = useState<number | null>(null);
  const [savingGithubNetuid, setSavingGithubNetuid] = useState<number | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const valueColCount = 6;
  const totalColCount = 3 + valueColCount + 1;

  useEffect(() => { if (expandedNetuid != null && !favoriteIds.includes(expandedNetuid)) setExpandedNetuid(null); }, [favoriteIds, expandedNetuid]);
  useEffect(() => {
    const d: Record<number, Record<string, string>> = {};
    for (const nu of favoriteIds) {
      const a = favoriteAlerts[nu] ?? {};
      d[nu] = {};
      for (const { key } of ALERT_METRIC_FIELDS) {
        const v = a[key];
        d[nu][key] = v != null && v > 0 ? String(v) : "";
      }
    }
    setDrafts(d);
  }, [favoriteIds, favoriteAlerts]);
  useEffect(() => {
    const g: Record<number, string> = {};
    for (const nu of favoriteIds) g[nu] = favoriteGithub[nu] ?? "";
    setGithubDrafts(g);
  }, [favoriteIds, favoriteGithub]);

  const countTriggers = (netuid: number) => ALERT_METRIC_FIELDS.filter((m) => Number((drafts[netuid]?.[m.key] ?? "").trim()) > 0).length;
  const setTriggerField = (netuid: number, key: string, value: string) => setDrafts((prev) => ({ ...prev, [netuid]: { ...(prev[netuid] ?? {}), [key]: value } }));
  const saveTriggers = async (netuid: number) => {
    setSavingNetuid(netuid); setSaveError(null);
    const body: FavoriteAlerts = {};
    for (const { key } of ALERT_METRIC_FIELDS) {
      const raw = (drafts[netuid]?.[key] ?? "").trim();
      if (!raw) { body[key] = null; continue; }
      const n = Number(raw);
      if (!Number.isFinite(n) || n <= 0) { setSaveError(`Subnet ${netuid}: enter a positive % or leave blank.`); setSavingNetuid(null); return; }
      body[key] = n;
    }
    try { onAlertsSaved(await fetchJson<FavoritesResponse>("/api/favorites/alerts", { method: "POST", body: JSON.stringify({ netuid, alerts: body }) })); }
    catch (e) { setSaveError(e instanceof Error ? e.message : String(e)); }
    finally { setSavingNetuid(null); }
  };
  const saveGithub = async (netuid: number) => {
    setSavingGithubNetuid(netuid); setSaveError(null);
    try { onAlertsSaved(await fetchJson<FavoritesResponse>("/api/favorites/github", { method: "POST", body: JSON.stringify({ netuid, github_url: (githubDrafts[netuid] ?? "").trim() || null }) })); }
    catch (e) { setSaveError(e instanceof Error ? e.message : String(e)); }
    finally { setSavingGithubNetuid(null); }
  };

  if (loading && !overviewData) return <p className="msg">Loading subnets…</p>;
  const missingCount = favoriteIds.filter((nu) => !rowsByNetuid.has(nu)).length;
  return <>
    {overviewData?.pool_warning ? <p className="msg warn">{overviewData.pool_warning}</p> : null}
    {overviewError ? <p className="msg warn">Last refresh issue: {overviewError}</p> : null}
    {saveError ? <p className="msg warn">{saveError}</p> : null}
    {missingCount > 0 ? <p className="msg footer-hint">{missingCount} favorite{missingCount === 1 ? "" : "s"} missing from latest overview.</p> : null}
    <p className="msg footer-hint compact-table-hint">Click a row to set alert |Δ%| thresholds and a GitHub repo URL. Blue % = change vs last refresh.</p>
    <div className="table-scroll"><table className="favorites-compact-table"><thead><tr><th className="favorite-col" aria-label="Favorite">★</th><th>#</th><th>Name</th>{ALERT_METRIC_FIELDS.map((m) => <th key={m.key} title={m.label}>{m.short}</th>)}<th className="expand-col" aria-label="Expand alerts"> </th></tr></thead><tbody>
      {favoriteIds.map((nu) => {
        const row = rowsByNetuid.get(nu);
        const d = deltas[nu];
        const expanded = expandedNetuid === nu;
        const triggerCount = countTriggers(nu);
        const hasGithub = Boolean((favoriteGithub[nu] ?? "").trim());
        const ar = row ? actualRewardTauPerDay(row.alpha_emission_tau_per_day ?? null, row.incentive_burn_rate) : null;
        return <Fragment key={nu}>
          <tr className={["fav-row-clickable", highlightNetuids.has(nu) ? "row-high-divergence" : "", expanded ? "fav-row-expanded" : ""].filter(Boolean).join(" ")} onClick={() => setExpandedNetuid((prev) => prev === nu ? null : nu)} tabIndex={0} role="button" aria-expanded={expanded} aria-controls={`fav-alerts-${nu}`}>
            <td className="favorite-col"><button type="button" className="fav-btn is-fav" disabled={favoritesToggling.has(nu)} onClick={(ev) => { ev.stopPropagation(); onToggleFavorite(nu); }} title="Unfavorite">★</button></td>
            <td><a href={`https://taostats.io/subnets/${nu}`} target="_blank" rel="noopener noreferrer" onClick={(ev) => ev.stopPropagation()}>{nu}</a></td>
            <td className="subnet-name-cell">{row?.name ?? "—"}</td>
            {row ? <><CompactMetricCell value={formatAlphaPrice(row.alpha_price_tao)} /><CompactMetricCell value={formatTaoDay(row.emission_tau_per_day)} delta={d?.emission} /><CompactMetricCell value={formatTaoDay(row.alpha_emission_tau_per_day ?? null)} delta={d?.alphaEmission} /><CompactMetricCell value={formatBurnPct(row.incentive_burn_rate)} delta={d?.burn} /><CompactMetricCell value={formatRegCostTau(row.neuron_registration_cost_tao)} delta={d?.reg} /><CompactMetricCell value={formatTaoDay(ar)} delta={d?.actualReward} /></> : <td colSpan={valueColCount} className="msg">—</td>}
            <td className="expand-col"><span className="expand-ind" aria-hidden="true">{expanded ? "▼" : "▶"}</span>{triggerCount > 0 ? <span className="trigger-badge">{triggerCount}</span> : null}{hasGithub ? <span className="trigger-badge github-badge" title="GitHub monitored">GH</span> : null}</td>
          </tr>
          {expanded ? <><tr className="fav-alerts-detail-row" id={`fav-alerts-${nu}`} onClick={(ev) => ev.stopPropagation()}><td colSpan={3} className="fav-alerts-lead-cell"><span className="fav-alerts-lead">|Δ%| ≥</span></td>{ALERT_METRIC_FIELDS.map((m) => <td key={m.key} className="fav-alert-cell" title={m.label}><div className="fav-alert-cell-inner"><span className="fav-alert-cell-label">{m.short}</span><input type="text" inputMode="decimal" className="alert-threshold-input" placeholder="—" value={drafts[nu]?.[m.key] ?? ""} onChange={(ev) => setTriggerField(nu, m.key, ev.target.value)} aria-label={`${m.label} threshold percent`} /></div></td>)}<td className="expand-col fav-alert-actions-cell"><button type="button" className="btn-sm" disabled={savingNetuid === nu} onClick={() => saveTriggers(nu)}>{savingNetuid === nu ? "…" : "Save"}</button>{triggerCount === 0 ? <span className="fav-alert-inline-warn">none</span> : null}</td></tr><tr className="fav-github-detail-row" onClick={(ev) => ev.stopPropagation()}><td colSpan={totalColCount} className="fav-github-cell"><div className="fav-github-inner"><label className="fav-github-label" htmlFor={`fav-github-${nu}`}>GitHub repo</label><input id={`fav-github-${nu}`} type="url" className="fav-github-input" placeholder="https://github.com/owner/repo" value={githubDrafts[nu] ?? ""} onChange={(ev) => setGithubDrafts((prev) => ({ ...prev, [nu]: ev.target.value }))} /><button type="button" className="btn-sm" disabled={savingGithubNetuid === nu} onClick={() => saveGithub(nu)}>{savingGithubNetuid === nu ? "…" : "Save GitHub"}</button><span className="fav-github-hint">New commits on the default branch post to Discord (<code>DISCORD_WEBHOOK_GITHUB_COMMIT</code>).</span></div></td></tr></> : null}
        </Fragment>;
      })}
    </tbody></table></div>
  </>;
}

const NOTIFY_CHANNEL_TELEGRAM = "telegram";
const NOTIFY_CHANNEL_DISCORD_FAVORITES = "discord_favorites";
const NOTIFY_CHANNEL_DISCORD_GITHUB = "discord_github_commit";

function buildChannelSettings(settings: NotificationSettingsResponse | null, tg: TelegramStatus | null, dc: DiscordStatus | null, gh: GithubMonitorStatus | null): NotificationChannelSetting[] {
  if (settings?.channels?.length) return settings.channels;
  return [
    { id: NOTIFY_CHANNEL_TELEGRAM, label: "Telegram", configured: Boolean(tg?.configured), enabled: tg?.enabled ?? true, active: tg?.active ?? Boolean(tg?.configured) },
    { id: NOTIFY_CHANNEL_DISCORD_FAVORITES, label: "Discord · favorites", configured: Boolean(dc?.favorites_configured), enabled: dc?.favorites_enabled ?? true, active: dc?.favorites_active ?? Boolean(dc?.favorites_configured) },
    { id: NOTIFY_CHANNEL_DISCORD_GITHUB, label: "Discord · GitHub commits", configured: Boolean(gh?.configured), enabled: gh?.enabled ?? true, active: gh?.active ?? Boolean(gh?.configured) },
  ];
}

export function FavoriteNotificationsSettings({ favoriteCount }: { favoriteCount: number }) {
  const [channelSettings, setChannelSettings] = useState<NotificationChannelSetting[]>([]);
  const [tgStatus, setTgStatus] = useState<TelegramStatus | null>(null);
  const [dcStatus, setDcStatus] = useState<DiscordStatus | null>(null);
  const [ghStatus, setGhStatus] = useState<GithubMonitorStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [togglingChannel, setTogglingChannel] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    const results = await Promise.allSettled([fetchJson<NotificationSettingsResponse>("/api/notifications/settings"), fetchJson<TelegramStatus>("/api/notifications/telegram/status"), fetchJson<DiscordStatus>("/api/notifications/discord/status"), fetchJson<GithubMonitorStatus>("/api/notifications/github/status")]);
    const settings = results[0].status === "fulfilled" ? results[0].value : null;
    const tg = results[1].status === "fulfilled" ? results[1].value : null;
    const dc = results[2].status === "fulfilled" ? results[2].value : null;
    const gh = results[3].status === "fulfilled" ? results[3].value : null;
    if (tg) setTgStatus(tg); if (dc) setDcStatus(dc); if (gh) setGhStatus(gh);
    setChannelSettings(buildChannelSettings(settings, tg, dc, gh));
    setLoadError(!tg && !dc && !gh ? "Could not reach notification API" : null);
  }, []);
  useEffect(() => { refreshStatus(); }, [refreshStatus]);

  const toggleChannel = async (channelId: string, enabled: boolean) => {
    setTogglingChannel(channelId);
    try {
      const resp = await fetchJson<NotificationSettingsResponse>("/api/notifications/channel", { method: "POST", body: JSON.stringify({ channel: channelId, enabled }) });
      setChannelSettings(resp.channels);
      setLoadError(null);
    } catch (e) { setLoadError(e instanceof Error ? e.message : String(e)); }
    finally { setTogglingChannel(null); }
  };
  const test = async (id: string, path: string, body: object) => {
    setTesting(id); setTestResult(null);
    try { await fetchJson<{ ok: boolean }>(path, { method: "POST", body: JSON.stringify(body) }); setTestResult("Sent. Check the configured channel."); }
    catch (e) { setTestResult(e instanceof Error ? e.message : String(e)); }
    finally { setTesting(null); }
  };
  const byId = (id: string) => channelSettings.find((c) => c.id === id);
  const renderChannel = (id: string, title: string, configured: boolean, missing: string, testPath: string, testBody: object) => {
    const ch = byId(id);
    return <div className="notify-channel-block"><h4 className="notify-channel-title">{title}</h4>{configured ? <p className="msg"><span className="badge ok">configured</span> <span className={ch?.active ? "badge ok" : "badge bad"}>{ch?.active ? "alerts on" : "disabled"}</span></p> : <p className="msg warn"><span className="badge bad">not configured</span> {missing}</p>}<div className="row notify-channel-actions">{configured ? <button type="button" className={ch?.enabled ? "btn-sm channel-toggle on" : "btn-sm channel-toggle off"} disabled={togglingChannel === id} onClick={() => toggleChannel(id, !(ch?.enabled ?? true))}>{togglingChannel === id ? "…" : ch?.enabled ? "Disable" : "Enable"}</button> : null}<button type="button" className="btn-sm" disabled={testing === id || !configured} onClick={() => test(id, testPath, testBody)}>{testing === id ? "Sending…" : "Test"}</button></div></div>;
  };
  const intervalMin = tgStatus?.interval_sec != null ? Math.max(1, Math.round(tgStatus.interval_sec / 60)) : dcStatus?.interval_sec != null ? Math.max(1, Math.round(dcStatus.interval_sec / 60)) : null;
  return <div className="notification-settings"><p className="msg footer-hint">Polls every {intervalMin ?? "—"} min; sends when a favorite crosses its |Δ%| threshold. {favoriteCount === 1 ? "1 favorite" : `${favoriteCount} favorites`} monitored.</p>{loadError ? <p className="msg warn">Could not load notification status: {loadError}</p> : null}{renderChannel(NOTIFY_CHANNEL_TELEGRAM, "Telegram", Boolean(tgStatus?.configured), "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID", "/api/notifications/telegram/test", {})}{renderChannel(NOTIFY_CHANNEL_DISCORD_FAVORITES, "Discord · favorites", Boolean(dcStatus?.favorites_configured), "Set DISCORD_WEBHOOK_FAVORITES in .env", "/api/notifications/discord/test", { channel: "favorites" })}{renderChannel(NOTIFY_CHANNEL_DISCORD_GITHUB, "Discord · GitHub commits", Boolean(ghStatus?.configured), "Set DISCORD_WEBHOOK_GITHUB_COMMIT in .env", "/api/notifications/discord/test", { channel: "github_commit", text: "**bittensor-tools**: GitHub commit alerts are wired up." })}{ghStatus?.configured ? <p className="msg footer-hint">Monitoring {ghStatus.monitored_count} GitHub repo{ghStatus.monitored_count === 1 ? "" : "s"}.</p> : null}{testResult ? <p className="msg">{testResult}</p> : null}<div className="row"><button type="button" className="btn-sm btn-muted" onClick={refreshStatus}>Recheck all</button></div></div>;
}
