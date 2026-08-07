// GridVision — types mirroring api/main.py's JSON shapes.

export interface RegionProperties {
  code: string;
  name: string;
  peak_forecast_mw: number | null;
  delta_vs_prior_run_mw: number | null;
  temperature: number | null;
  model_version: string | null;
  updated_at: string | null;
}

export interface RegionFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: RegionProperties;
}

export interface RegionsResponse {
  type: "FeatureCollection";
  features: RegionFeature[];
}

export interface ForecastHour {
  ts: string;
  p10: number;
  p50: number;
  p90: number;
  model_version: string;
}

export interface ForecastResponse {
  region: string;
  hours: ForecastHour[];
}

export interface Decision {
  decided_at: string;
  decision: "promote" | "reject";
  version: string;
  candidate_mape: number;
  production_mape: number | null;
  baseline_mape: number;
  reason: string;
}

export interface HistoryResponse {
  decisions: Decision[];
}

export interface CoverageProperties {
  code: string;
  name: string;
  radius_km: number;
}

export interface CoverageFeature {
  type: "Feature";
  geometry: { type: "Polygon"; coordinates: number[][][] };
  properties: CoverageProperties;
}

export interface CoverageResponse {
  type: "FeatureCollection";
  features: CoverageFeature[];
}
