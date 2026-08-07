// GridVision — 3D demand map, deck.gl rendering on a dark CARTO basemap.
//
// Only 9 points exist (one per balancing authority, from config.REGIONS'
// lat/lon), so the deliberate techniques here are: deck.gl's ColumnLayer for
// real lit/shaded 3D cylinders (not hand-built polygon boxes — MapLibre's
// fill-extrusion has no lighting model and looks flat), and a HeatmapLayer
// underneath for ambient glow so the sparse points don't read as empty. Both
// share the same sequential blue ramp used in the chart/sidebar, so color
// means "more demand" consistently across the whole dashboard.
import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ColumnLayer } from "@deck.gl/layers";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import { fetchRegions } from "./api";
import { colorForDemandRGB } from "./colorScale";
import type { RegionFeature } from "./types";

const DARK_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const ELEVATION_SCALE = 3;
const COLUMN_RADIUS_M = 45000;

interface PointDatum {
  code: string;
  name: string;
  lon: number;
  lat: number;
  peak: number;
  delta: number;
}

interface Props {
  onSelectRegion: (code: string) => void;
  selected: string | null;
}

export default function DemandMap({ onSelectRegion, selected }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const pointsRef = useRef<PointDatum[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; d: PointDatum } | null>(null);

  const buildLayers = (points: PointDatum[], selectedCode: string | null) => [
    new HeatmapLayer<PointDatum>({
      id: "glow",
      data: points,
      getPosition: (d) => [d.lon, d.lat],
      getWeight: (d) => d.peak,
      radiusPixels: 90,
      intensity: 1.4,
      threshold: 0.02,
      colorRange: [
        [13, 54, 107, 0],
        [24, 79, 149, 80],
        [42, 120, 214, 140],
        [109, 167, 236, 200],
        [183, 211, 246, 255],
      ],
    }),
    new ColumnLayer<PointDatum>({
      id: "columns",
      data: points,
      diskResolution: 24,
      radius: COLUMN_RADIUS_M,
      extruded: true,
      elevationScale: ELEVATION_SCALE,
      getPosition: (d) => [d.lon, d.lat],
      getElevation: (d) => d.peak,
      getFillColor: (d) => {
        const [r, g, b] = colorForDemandRGB(d.peak);
        const isSelected = d.code === selectedCode;
        // Brighten the selected column instead of drawing a border ring —
        // keeps the "no stroke as separator" rule from the dataviz skill.
        return isSelected ? [Math.min(255, r + 60), Math.min(255, g + 60), Math.min(255, b + 60), 255] : [r, g, b, 200];
      },
      pickable: true,
      onHover: (info) => {
        if (info.object) {
          setTooltip({ x: info.x, y: info.y, d: info.object as PointDatum });
        } else {
          setTooltip(null);
        }
      },
      onClick: (info) => {
        if (info.object) onSelectRegion((info.object as PointDatum).code);
      },
      updateTriggers: {
        getFillColor: [selectedCode],
      },
    }),
  ];

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: DARK_STYLE,
      center: [-98, 39],
      zoom: 3.5,
      pitch: 55,
      bearing: -12,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

    map.on("load", async () => {
      try {
        const regions = await fetchRegions();
        const points: PointDatum[] = regions.features.map((f: RegionFeature) => ({
          code: f.properties.code,
          name: f.properties.name,
          lon: f.geometry.coordinates[0],
          lat: f.geometry.coordinates[1],
          peak: f.properties.peak_forecast_mw ?? 0,
          delta: f.properties.delta_vs_prior_run_mw ?? 0,
        }));
        pointsRef.current = points;

        const overlay = new MapboxOverlay({ interleaved: true, layers: buildLayers(points, selected) });
        overlayRef.current = overlay;
        map.addControl(overlay);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onSelectRegion]);

  // Re-render layers (brighten the selected column) without refetching data.
  useEffect(() => {
    if (overlayRef.current && pointsRef.current.length) {
      overlayRef.current.setProps({ layers: buildLayers(pointsRef.current, selected) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
      <div className="map-legend">
        <div className="map-legend-title">Peak forecast demand</div>
        <div className="map-legend-scale" />
        <div className="map-legend-labels">
          <span>Lower</span>
          <span>Higher</span>
        </div>
      </div>
      {tooltip && (
        <div className="gv-deck-tooltip" style={{ left: tooltip.x + 12, top: tooltip.y + 12 }}>
          <strong>{tooltip.d.name}</strong>
          <div>Peak forecast: {Math.round(tooltip.d.peak).toLocaleString()} MW</div>
          <div>Δ vs prior run: {Math.round(tooltip.d.delta).toLocaleString()} MW</div>
        </div>
      )}
      {error && (
        <div className="map-error">
          Failed to load regions: {error}
          <br />
          (Is the API running? <code>uvicorn api.main:app --port 8000</code>)
        </div>
      )}
    </div>
  );
}
