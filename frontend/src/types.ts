export interface DashboardConfig {
  min_divergence_pct: number;
  lookback_sec: number;
  lookback_tolerance_sec: number;
  snapshot_path: string;
  taostats_api_url: string;
  taomarketcap_api_url?: string;
  taomarketcap_request_timeout_sec?: number;
  taomarketcap_cache_ttl_sec?: number;
  taomarketcap_daily_refresh_hour?: number;
  taomarketcap_daily_refresh_minute?: number;
  request_timeout_sec: number;
  /** Path of favorites.yaml on disk (resolved). */
  favorites_config_path?: string;
  /** Default favorites.yaml path bundled with the repo. */
  favorites_default_path?: string;
  /** How often the backend pushes a Telegram favorites digest (seconds). */
  favorites_notify_interval_sec?: number;
  /** True when both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set. */
  telegram_configured?: boolean;
  /** True when DISCORD_WEBHOOK_FAVORITES is set. */
  discord_favorites_configured?: boolean;
  /** True when DISCORD_WEBHOOK_GITHUB_COMMIT is set. */
  discord_github_commit_configured?: boolean;
  github_commit_poll_interval_sec?: number;
  github_monitor_configured?: boolean;
  /** True when Telegram and/or Discord favorites webhook is configured. */
  favorites_alerts_configured?: boolean;
  /** Resolved path to repo ``.env`` loaded at startup. */
  env_file_path?: string;
  bittensor_network_override: string | null;
  dashboard_host: string;
  dashboard_port: number;
}

/** Per-metric |Δ%| threshold; null/omitted = do not alert on that metric. */
export interface FavoriteAlerts {
  alpha_price_pct?: number | null;
  alpha_emission_pct?: number | null;
  root_emission_pct?: number | null;
  burn_pct?: number | null;
  reg_pct?: number | null;
  actual_reward_pct?: number | null;
}

export interface FavoriteEntry {
  netuid: number;
  alerts: FavoriteAlerts;
  github_url?: string | null;
}

/** API may return legacy ``number[]`` during migration. */
export interface FavoritesResponse {
  favorites: number[] | FavoriteEntry[];
}

export interface NotificationChannelSetting {
  id: string;
  label: string;
  configured: boolean;
  enabled: boolean;
  active: boolean;
}

export interface NotificationSettingsResponse {
  config_path: string;
  channels: NotificationChannelSetting[];
}

export interface TelegramStatus {
  configured: boolean;
  enabled?: boolean;
  active?: boolean;
  has_token: boolean;
  has_chat_id: boolean;
  interval_sec: number;
}

export interface DiscordChannelStatus {
  key: string;
  configured: boolean;
  env_var: string;
}

export interface DiscordStatus {
  channels: DiscordChannelStatus[];
  favorites_channel: string;
  favorites_configured: boolean;
  favorites_enabled?: boolean;
  favorites_active?: boolean;
  github_commit_channel?: string;
  github_commit_configured?: boolean;
  github_commit_enabled?: boolean;
  github_commit_active?: boolean;
  interval_sec: number;
}

export interface GithubMonitorStatus {
  configured: boolean;
  enabled?: boolean;
  active?: boolean;
  poll_interval_sec: number;
  discord_channel: string;
  env_var: string;
  monitored_count: number;
  monitored: { netuid: number; github_url: string | null }[];
}

export interface SubnetOverviewRow {
  netuid: number;
  name: string;
  alpha_price_tao: number | null;
  /**
   * Mainnet TAO into the subnet pool (τ/day): subnet/latest `emission` (rao/block) ÷ 1e9 × blocks/day.
   */
  emission_tau_per_day: number | null;
  /**
   * Subnet alpha emission to participants, valued in TAO (τ/day): dTAO subnet_emission `alpha_rewards`
   * (α/block in rao) ÷ 1e9 × pool price (τ/α) × blocks/day; null if emission row, price, or field missing.
   */
  /** Present after backend adds dTAO subnet_emission merge; omit on older servers. */
  alpha_emission_tau_per_day?: number | null;
  /** Current neuron registration burn in τ (rao/1e9 from subnet/latest); null if field missing */
  neuron_registration_cost_tao: number | null;
  /** incentive_burn hyperparameter (0–1); null if absent */
  incentive_burn_rate: number | null;
  github_repo?: string | null;
  logo_url?: string | null;
  subnet_url?: string | null;
}

export interface TaostatsOverviewResponse {
  fetched_at: number;
  subnets: SubnetOverviewRow[];
  pool_warning: string | null;
  /** Blocks per day used for τ/day (env TAOSTATS_BLOCKS_PER_DAY); default 7200 */
  blocks_per_day?: number;
}

export interface TaoMarketCapMinerReward {
  rank: number;
  uid?: number;
  netuid: number;
  hotkey: string;
  coldkey: string;
  percentage?: number | null;
  total_alpha?: number | null;
  total_alpha_rao?: number | null;
  tao_stake?: number | null;
  realized_pnl_tao?: number | null;
  unrealized_pnl_tao?: number | null;
  alpha_per_day: number | null;
  tao_per_day: number | null;
  incentive?: number | null;
  miner_performance?: number | null;
  flagged?: boolean;
}

export interface TaoMarketCapRewardHistoryDay {
  date: string;
  fetched_at: number;
  daily_reward_count?: number;
  total_alpha_per_day?: number | null;
  total_tao_per_day?: number | null;
  daily_rewards?: TaoMarketCapMinerReward[];
}

export interface TaoMarketCapSubnetMinersResponse {
  netuid: number;
  fetched_at: number;
  cached_at?: number;
  cache_hit?: boolean;
  cache_ttl_sec?: number;
  cache_expires_at?: number;
  source: string;
  price_tao_per_alpha?: number | null;
  total_count?: number;
  miner_count: number;
  daily_reward_count?: number;
  total_alpha?: number | null;
  total_alpha_per_day?: number | null;
  total_tao_per_day?: number | null;
  total_realized_pnl_tao?: number | null;
  total_unrealized_pnl_tao?: number | null;
  miners: TaoMarketCapMinerReward[];
  daily_rewards?: TaoMarketCapMinerReward[];
  available_reward_days?: string[];
  reward_history?: TaoMarketCapRewardHistoryDay[];
  current_reward_day?: TaoMarketCapRewardHistoryDay | null;
  previous_reward_day?: TaoMarketCapRewardHistoryDay | null;
}

export interface DivergenceRow {
  netuid: number;
  emission_pct_per_day: number | null;
  burn_pct_per_day: number | null;
  divergence_pct_points: number;
  emission_now: string;
  burn_now: string;
  emission_then: string | null;
  burn_then: string | null;
}

export interface TaostatsDivergenceResponse {
  warning: string | null;
  subnet_count: number;
  snapshot_time: number | null;
  baseline_time: number | null;
  divergences: DivergenceRow[];
  min_divergence_pct: number;
  lookback_sec: number;
  lookback_tolerance_sec: number;
  snapshot_path: string;
  /** True when loaded from disk via GET /api/taostats/divergence/snapshot (no live Taostats run). */
  from_snapshot_file?: boolean;
}

export interface TaoDailyNewsItem {
  title: string;
  excerpt: string;
  link: string;
  published_at: string;
  published_date: string;
  image_url?: string | null;
  image_alt?: string | null;
}

export interface TaoDailyNewsResponse {
  source: string;
  fetched_at: number;
  date_range: string[];
  items: TaoDailyNewsItem[];
}
