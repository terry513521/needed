import type { TaoDailyNewsItem, TaoDailyNewsResponse } from "../../types";
import { formatUnixSeconds } from "../../utils/format";

function AlarmNewsCard({ item }: { item: TaoDailyNewsItem }) {
  return (
    <article className="alarm-card">
      {item.image_url ? (
        <a className="alarm-image-link" href={item.link} target="_blank" rel="noreferrer" tabIndex={-1}>
          <img className="alarm-image" src={item.image_url} alt={item.image_alt || item.title} loading="lazy" />
        </a>
      ) : null}
      <div className="alarm-card-body">
        <span className="alarm-date">{new Date(item.published_at).toLocaleString()}</span>
        <h3><a href={item.link} target="_blank" rel="noreferrer">{item.title}</a></h3>
        <p>{item.excerpt}</p>
      </div>
    </article>
  );
}

export function AlarmsPanel({ data, loading, error, compact = false }: {
  data: TaoDailyNewsResponse | null;
  loading: boolean;
  error: string | null;
  compact?: boolean;
}) {
  const fetchedAt = data?.fetched_at ? formatUnixSeconds(data.fetched_at) : null;
  return (
    <section className={compact ? "alarms-panel compact" : "alarms-panel"}>
      <span className="eyebrow">Alarms</span>
      <h2>Welcome to  our Grit Team</h2>
      <p className="sub">Today and yesterday&apos;s TAO ecosystem news from <a href="https://taodaily.io/" target="_blank" rel="noreferrer">TAO Daily</a>{fetchedAt ? <> · fetched {fetchedAt}</> : null}.</p>
      {loading ? (
        <div className="alarm-loading-card" aria-label="Loading today and yesterday's news">
          <div className="alarm-loading-image" aria-hidden="true" />
          <p className="msg">Loading TAO Daily alarms…</p>
        </div>
      ) : null}
      {error ? <p className="msg warn">Could not load TAO Daily news: {error}</p> : null}
      {!loading && !error && data?.items.length === 0 ? <p className="msg">No TAO Daily posts found for today or yesterday.</p> : null}
      <div className="alarm-news-grid">
        {data?.items.map((item) => (
          <AlarmNewsCard item={item} key={`${item.published_at}:${item.link}`} />
        ))}
      </div>
    </section>
  );
}

export function AlarmsModal({
  data,
  loading,
  error,
  onClose,
}: {
  data: TaoDailyNewsResponse | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop alarm-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div
        className="miner-modal alarm-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="alarm-modal-title"
        onMouseDown={(ev) => ev.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <h2 id="alarm-modal-title">Today & Yesterday&apos;s News</h2>
            <p className="msg">Today and yesterday&apos;s TAO Daily updates.</p>
          </div>
          <button type="button" className="btn-sm btn-muted modal-close" onClick={onClose}>
            Close
          </button>
        </div>
        <AlarmsPanel data={data} loading={loading} error={error} compact />
      </div>
    </div>
  );
}
