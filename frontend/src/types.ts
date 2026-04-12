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
