import { useEffect, useState } from "react";
import DemandMap from "./DemandMap";
import ForecastChart from "./ForecastChart";
import PromotionTimeline from "./PromotionTimeline";
import { fetchForecast, fetchRegions } from "./api";
import { formatMW, formatDelta } from "./format";
import { colorForDemandHex } from "./colorScale";
import type { RegionFeature } from "./types";
import "./App.css";

function StatTile({ label, value, delta }: { label: string; value: string; delta?: { text: string; positive: boolean } }) {
  return (
    <div className="stat-tile">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {delta && (
        <div className={`stat-delta ${delta.positive ? "up" : "down"}`}>
          {delta.positive ? "▲" : "▼"} {delta.text}
        </div>
      )}
    </div>
  );
}

function App() {
  const [selected, setSelected] = useState<string | null>(null);
  const [region, setRegion] = useState<RegionFeature | null>(null);
  const [nextHourP50, setNextHourP50] = useState<number | null>(null);

  useEffect(() => {
    if (!selected) return;
    fetchRegions().then((data) => {
      setRegion(data.features.find((f) => f.properties.code === selected) ?? null);
    });
    fetchForecast(selected).then((data) => {
      setNextHourP50(data.hours[0]?.p50 ?? null);
    });
  }, [selected]);

  const delta = region?.properties.delta_vs_prior_run_mw ?? null;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-dot" aria-hidden="true" />
          <h1>GridVision</h1>
        </div>
        <span className="tagline">Live US energy demand forecast — click a region</span>
      </header>

      <div className="app-body">
        <main className="app-main">
          <DemandMap onSelectRegion={setSelected} selected={selected} />
          <aside className="sidebar">
            {!region && (
              <div className="empty-state">
                <p>Click a region on the map to see its forecast.</p>
              </div>
            )}
            {region && (
              <>
                <div className="sidebar-heading">
                  <span
                    className="region-swatch"
                    style={{ background: colorForDemandHex(region.properties.peak_forecast_mw ?? 0) }}
                    aria-hidden="true"
                  />
                  <div>
                    <span className="region-code">{region.properties.code}</span>
                    <h2>{region.properties.name}</h2>
                  </div>
                </div>
                <div className="stat-grid">
                  <StatTile label="Peak forecast (24h)" value={formatMW(region.properties.peak_forecast_mw)} />
                  <StatTile label="Next hour (P50)" value={nextHourP50 !== null ? formatMW(nextHourP50) : "…"} />
                  <StatTile
                    label="Vs prior run"
                    value={formatDelta(delta)}
                    delta={delta !== null ? { text: "since last forecast", positive: delta >= 0 } : undefined}
                  />
                  <StatTile label="Temperature" value={`${region.properties.temperature}°C`} />
                </div>
                <ForecastChart region={region.properties.code} />
                <div className="sidebar-footnote">
                  Served by model v{region.properties.model_version} · updated{" "}
                  {region.properties.updated_at ? new Date(region.properties.updated_at).toLocaleString() : "—"}
                </div>
              </>
            )}
          </aside>
        </main>
        <PromotionTimeline />
      </div>
    </div>
  );
}

export default App;
