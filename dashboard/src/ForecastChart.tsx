// GridVision — P10/P50/P90 forecast band chart for the selected region.
//
// Recharts has no native "range band" mark, so the P10-P90 interval is built
// from the standard two-Area stack trick: an invisible Area up to P10, then a
// visible Area of height (P90-P10) on top of it. One hue (sequential blue),
// wash opacity per the dataviz skill's mark spec (~10%, never a saturated
// block); the P50 line is the only fully-opaque mark, since it's the number
// that answers "what will demand be."
import { useEffect, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchForecast } from "./api";
import { formatMW } from "./format";

interface Props {
  region: string;
}

interface ChartRow {
  ts: string;
  hourLabel: string;
  p10: number;
  p50: number;
  p90: number;
  band: number;
}

// Compact "11a" / "3p" style instead of "11 AM" — shorter labels leave more
// room before adjacent ticks collide.
function compactHour(ts: string): string {
  const h = new Date(ts).getHours();
  const period = h < 12 ? "a" : "p";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}${period}`;
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { payload: ChartRow }[] }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-time">{row.hourLabel}</div>
      <div>P90 (high case): {formatMW(row.p90)}</div>
      <div className="chart-tooltip-p50">P50 (forecast): {formatMW(row.p50)}</div>
      <div>P10 (low case): {formatMW(row.p10)}</div>
    </div>
  );
}

export default function ForecastChart({ region }: Props) {
  const [rows, setRows] = useState<ChartRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchForecast(region).then((data) => {
      setRows(
        data.hours.map((h) => ({
          ts: h.ts,
          hourLabel: compactHour(h.ts),
          p10: h.p10,
          p50: h.p50,
          p90: h.p90,
          band: h.p90 - h.p10,
        }))
      );
      setLoading(false);
    });
  }, [region]);

  if (loading) return <div className="chart-empty">Loading forecast…</div>;
  if (!rows.length) return <div className="chart-empty">No forecast available.</div>;

  return (
    <div className="chart-card">
      <div className="chart-caption">
        24h forecast — shaded band is the 80% interval (P10–P90), line is the median (P50)
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="0" stroke="#e1e0d9" vertical={false} />
          <XAxis
            dataKey="hourLabel"
            tick={{ fontSize: 11, fill: "#898781" }}
            axisLine={{ stroke: "#c3c2b7" }}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={28}
          />
          <YAxis
            tickFormatter={(v) => formatMW(v)}
            tick={{ fontSize: 11, fill: "#898781" }}
            axisLine={false}
            tickLine={false}
            width={64}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area dataKey="p10" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} />
          <Area
            dataKey="band"
            stackId="band"
            stroke="none"
            fill="#2a78d6"
            fillOpacity={0.12}
            isAnimationActive={false}
          />
          <Line dataKey="p50" stroke="#2a78d6" strokeWidth={2} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
