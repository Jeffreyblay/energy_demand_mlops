// GridVision — thin fetch wrapper around the FastAPI backend.
// Points at the local uvicorn dev server; swap via VITE_API_BASE for other envs.

import type { RegionsResponse, ForecastResponse, HistoryResponse, CoverageResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`${path} -> HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const fetchRegions = () => getJSON<RegionsResponse>("/regions");

export const fetchForecast = (region: string) =>
  getJSON<ForecastResponse>(`/forecast?region=${encodeURIComponent(region)}`);

export const fetchHistory = (limit = 20) =>
  getJSON<HistoryResponse>(`/history?limit=${limit}`);

export const fetchCoverage = (radiusKm = 80) =>
  getJSON<CoverageResponse>(`/regions/coverage?radius_km=${radiusKm}`);
