import { useMemo, useState } from "react";
import type { TaoMarketCapMinerReward, TaoMarketCapRewardHistoryDay, TaoMarketCapSubnetMinersResponse } from "../../types";
import { compactAddress, formatCompactAmount, formatTaoDay, formatUnixSeconds } from "../../utils/format";

function formatRewardDayLabel(day: string): string {
  const date = new Date(`${day}T00:00:00`);
  if (Number.isNaN(date.getTime())) return day;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function DailyRewardBarChart({
  miners,
  selectedHistoryDay,
  selectedDayIndex,
  navigationNotice,
  onPreviousDay,
  onNextDay,
}: {
  miners: TaoMarketCapMinerReward[];
  selectedHistoryDay: TaoMarketCapRewardHistoryDay | null;
  selectedDayIndex: number;
  navigationNotice: string;
  onPreviousDay: () => void;
  onNextDay: () => void;
}) {
  const rows = miners.filter((m) => m.tao_per_day != null && Number.isFinite(m.tao_per_day)).slice(0, 12);
  const maxReward = Math.max(...rows.map((m) => m.tao_per_day ?? 0), 0);
  if (!rows.length || maxReward <= 0) return <p className="msg">No daily TAO reward chart data available.</p>;
  const yTicks = [maxReward, maxReward * 0.75, maxReward * 0.5, maxReward * 0.25, 0];
  return (
    <div className="chart-card reward-chart-card">
      <div className="chart-header">
        <h3>Miner daily TAO reward</h3>
        <div className="reward-day-selector" aria-label="Select reward day">
          <button
            type="button"
            className="btn-sm btn-muted reward-day-btn"
            onClick={onPreviousDay}
            aria-label="Show previous day's miner rewards"
            title="Previous day"
          >
            ←
          </button>
          <span className="reward-day-current" title={selectedHistoryDay?.date ?? undefined}>
            {selectedHistoryDay ? formatRewardDayLabel(selectedHistoryDay.date) : "No day"}
          </span>
          <button
            type="button"
            className="btn-sm btn-muted reward-day-btn"
            onClick={onNextDay}
            disabled={selectedDayIndex <= 0}
            aria-label="Show next day's miner rewards"
            title="Next day"
          >
            →
          </button>
        </div>
      </div>
      {navigationNotice ? <p className="msg reward-day-notice">{navigationNotice}</p> : null}
      <div className="vertical-chart" aria-label="Miner daily TAO reward bar chart">
        <div className="y-axis" aria-hidden="true">{yTicks.map((tick) => <span key={tick}>{formatCompactAmount(tick)}</span>)}</div>
        <div className="vertical-plot">
          <div className="grid-lines" aria-hidden="true">{yTicks.map((tick) => <span key={tick} />)}</div>
          <div className="vertical-bars">
            {rows.map((m) => {
              const reward = m.tao_per_day ?? 0;
              const height = Math.max(4, (reward / maxReward) * 100);
              return (
                <div className="vertical-bar-item" key={`reward:${m.rank}:${m.hotkey || m.coldkey}`}>
                  <div className="vertical-bar-wrap"><span className="vertical-bar-fill" style={{ height: `${height}%` }}><span className="vertical-bar-value">{formatCompactAmount(reward)} τ</span></span></div>
                  <div className="x-axis-links" aria-label={`Miner ${m.uid ?? m.rank} TaoMarketCap links`}>
                    <a href={`https://taomarketcap.com/hotkey/${encodeURIComponent(m.hotkey)}`} target="_blank" rel="noreferrer" title={m.hotkey}>{compactAddress(m.hotkey)}</a>
                    <a href={`https://taomarketcap.com/coldkey/${encodeURIComponent(m.coldkey)}`} target="_blank" rel="noreferrer" title={m.coldkey}>{compactAddress(m.coldkey)}</a>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

export function MinerRewardsModal({ netuid, subnetName, data, loading, error, onClose }: {
  netuid: number;
  subnetName: string | null;
  data: TaoMarketCapSubnetMinersResponse | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  const historyDays = useMemo(() => {
    const explicitDays = [data?.current_reward_day, data?.previous_reward_day]
      .filter((day): day is TaoMarketCapRewardHistoryDay => Boolean(day?.daily_rewards?.length));
    if (explicitDays.length) {
      const extraDays = data?.reward_history?.filter(
        (day) => day.daily_rewards?.length && !explicitDays.some((explicitDay) => explicitDay.date === day.date),
      ) ?? [];
      return [...explicitDays, ...extraDays];
    }
    const fromHistory = data?.reward_history?.filter((day) => day.daily_rewards?.length) ?? [];
    if (fromHistory.length) return fromHistory;
    if (data?.daily_rewards?.length) {
      return [{
        date: new Date((data.cached_at ?? data.fetched_at) * 1000).toISOString().slice(0, 10),
        fetched_at: data.cached_at ?? data.fetched_at,
        daily_reward_count: data.daily_reward_count,
        total_alpha_per_day: data.total_alpha_per_day,
        total_tao_per_day: data.total_tao_per_day,
        daily_rewards: data.daily_rewards,
      }];
    }
    return [];
  }, [data]);
  const [selectedDayIndexOverride, setSelectedDayIndexOverride] = useState<number | null>(null);
  const [navigationNotice, setNavigationNotice] = useState("");
  const selectedDayIndex = Math.min(
    Math.max(selectedDayIndexOverride ?? 0, 0),
    Math.max(historyDays.length - 1, 0),
  );
  const selectedHistoryDay = historyDays[selectedDayIndex] ?? null;
  const rewardRows = selectedHistoryDay?.daily_rewards?.length ? selectedHistoryDay.daily_rewards : data?.miners ?? [];
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="miner-modal" role="dialog" aria-modal="true" aria-labelledby="miner-modal-title" onMouseDown={(ev) => ev.stopPropagation()}>
        <div className="modal-header"><div><span className="eyebrow modal-eyebrow">Subnet status</span><h2 id="miner-modal-title">Subnet {netuid}{subnetName ? <span className="modal-title-muted"> · {subnetName}</span> : null}</h2><p className="msg">Miner reward rows from TaoMarketCap neurons API. The bar chart uses α/day converted to τ/day.</p>{data ? <p className="msg cache-hint">{data.cache_hit ? "Served from backend cache" : "Freshly fetched and cached"}{data.cache_expires_at ? ` · refreshes after ${formatUnixSeconds(data.cache_expires_at)}` : ""}</p> : null}</div><button type="button" className="btn-sm btn-muted modal-close" onClick={onClose}>Close</button></div>
        {loading ? <p className="msg">Loading miner rewards…</p> : null}
        {error ? <p className="msg warn">Could not load miner rewards: {error}</p> : null}
        {data ? <>
          <div className="miner-summary-grid"><div className="miner-summary-card"><span className="miner-summary-value">{data.total_count ?? data.miner_count}</span><span className="miner-summary-label">Total miners</span></div><div className="miner-summary-card"><span className="miner-summary-value">{selectedHistoryDay?.daily_reward_count ?? rewardRows.length}</span><span className="miner-summary-label">Reward rows</span></div><div className="miner-summary-card"><span className="miner-summary-value">{formatTaoDay(data.total_alpha ?? null)}</span><span className="miner-summary-label">Loaded α stake</span></div><div className="miner-summary-card"><span className="miner-summary-value">{formatTaoDay(rewardRows[0]?.tao_per_day ?? null)}</span><span className="miner-summary-label">Top miner τ/day</span></div></div>
          <DailyRewardBarChart
            miners={rewardRows}
            selectedHistoryDay={selectedHistoryDay}
            selectedDayIndex={selectedDayIndex}
            navigationNotice={navigationNotice}
            onPreviousDay={() => {
              if (selectedDayIndex >= historyDays.length - 1) {
                setNavigationNotice("No previous day's reward has been saved for this subnet yet.");
                return;
              }
              setNavigationNotice("");
              setSelectedDayIndexOverride((index) => Math.min((index ?? selectedDayIndex) + 1, Math.max(historyDays.length - 1, 0)));
            }}
            onNextDay={() => {
              setNavigationNotice("");
              setSelectedDayIndexOverride((index) => Math.max((index ?? selectedDayIndex) - 1, 0));
            }}
          />
          <div className="table-scroll miner-table-wrap"><table className="miner-rewards-table"><thead><tr><th>#</th><th>UID</th><th>Hotkey</th><th>Coldkey</th><th>α/day</th><th>τ/day</th><th>Incentive</th></tr></thead><tbody>{rewardRows.map((m) => <tr key={`${m.netuid}:${m.coldkey}:${m.rank}`}><td>{m.rank}</td><td>{m.uid ?? "—"}</td><td><code className="hk" title={m.hotkey}>{compactAddress(m.hotkey)}</code></td><td><code className="hk" title={m.coldkey}>{compactAddress(m.coldkey)}</code></td><td>{formatTaoDay(m.alpha_per_day)}</td><td><strong>{formatTaoDay(m.tao_per_day)}</strong></td><td>{m.incentive == null ? "—" : m.incentive.toFixed(6)}</td></tr>)}</tbody></table></div>
          <p className="msg footer-hint">Source: <code>{data.source}</code></p>
        </> : null}
      </div>
    </div>
  );
}
