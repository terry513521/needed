export interface DashboardConfig {
  min_divergence_pct: number;
  lookback_sec: number;
  lookback_tolerance_sec: number;
  snapshot_path: string;
  taostats_api_url: string;
  request_timeout_sec: number;
  hotkeys_config_path: string;
  /** Path of favorites.yaml on disk (resolved). */
  favorites_config_path?: string;
  /** Default favorites.yaml path bundled with the repo. */
  favorites_default_path?: string;
  /** How often the backend pushes a Telegram favorites digest (seconds). */
  favorites_notify_interval_sec?: number;
  /** True when both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set. */
  telegram_configured?: boolean;
  bittensor_network_override: string | null;
  dashboard_host: string;
  dashboard_port: number;
}

export interface FavoritesResponse {
  favorites: number[];
}

export interface TelegramStatus {
  configured: boolean;
  has_token: boolean;
  has_chat_id: boolean;
  interval_sec: number;
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
}

export interface TaostatsOverviewResponse {
  fetched_at: number;
  subnets: SubnetOverviewRow[];
  pool_warning: string | null;
  /** Blocks per day used for τ/day (env TAOSTATS_BLOCKS_PER_DAY); default 7200 */
  blocks_per_day?: number;
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

export interface HotkeyResult {
  name: string;
  netuid: number;
  hotkey: string;
  registered: boolean;
  uid: number | null;
  error: string | null;
}

export interface HotkeysCheckResponse {
  results: HotkeyResult[];
}

export interface HotkeyConfigEntry {
  name: string;
  netuid: number;
  hotkey: string;
}

export interface HotkeysConfigResponse {
  network: string;
  hotkeys: HotkeyConfigEntry[];
}
