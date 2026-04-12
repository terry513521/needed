export interface DashboardConfig {
  min_divergence_pct: number;
  lookback_sec: number;
  lookback_tolerance_sec: number;
  snapshot_path: string;
  taostats_api_url: string;
  request_timeout_sec: number;
  hotkeys_config_path: string;
  bittensor_network_override: string | null;
  dashboard_host: string;
  dashboard_port: number;
}

export interface SubnetOverviewRow {
  netuid: number;
  name: string;
  alpha_price_tao: number | null;
  /** TAO/day from subnet/latest projected_emission (τ/block) × blocks/day (≥ 0); null if absent */
  emission_tau_per_day: number | null;
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
