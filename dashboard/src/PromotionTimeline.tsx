// GridVision — daily model-check history, read from /history.
//
// The underlying concept is "promotion gate" (ML jargon), but this renders
// it in plain language: every day a freshly trained model is compared
// against the one currently live, and only takes over if it's measurably
// more accurate. A rejection is informative signal, not a failure — most
// days SHOULD say "no change," so this deliberately avoids red/danger color
// and alarm-sounding words for that outcome.
import { useEffect, useState } from "react";
import { fetchHistory } from "./api";
import type { Decision } from "./types";

function describe(d: Decision, isFirst: boolean) {
  if (isFirst && d.production_mape === null) {
    return {
      icon: "⚑", // flag
      headline: "First forecast model went live",
      detail: `Started producing daily forecasts, typically accurate to within ${d.candidate_mape.toFixed(1)}%.`,
    };
  }
  if (d.decision === "promote") {
    return {
      icon: "✓", // check
      headline: "Switched to a more accurate model",
      detail:
        d.production_mape !== null
          ? `New forecasts are typically off by ${d.candidate_mape.toFixed(1)}%, versus ${d.production_mape.toFixed(1)}% before.`
          : `Typically accurate to within ${d.candidate_mape.toFixed(1)}%.`,
    };
  }
  return {
    icon: "–", // en dash, neutral "no change"
    headline: "No change today",
    detail: `Today's newly trained model wasn't more accurate than the one already running, so forecasts stayed as-is.`,
  };
}

export default function PromotionTimeline() {
  const [decisions, setDecisions] = useState<Decision[] | null>(null);

  useEffect(() => {
    fetchHistory(14).then((data) => setDecisions([...data.decisions].reverse()));
  }, []);

  if (decisions === null) return null;
  if (!decisions.length) {
    return <div className="timeline-empty">No history yet — check back after the first daily run.</div>;
  }

  return (
    <div className="timeline">
      <div className="timeline-heading">
        Daily model checks
        <span className="timeline-subhead">
          {" "}
          — each day a freshly trained model is compared to the one running live; it only takes over if it's more accurate.
        </span>
      </div>
      <div className="timeline-track">
        {decisions.map((d, i) => {
          const { icon, headline, detail } = describe(d, i === 0);
          return (
            <div className="timeline-node" key={d.decided_at}>
              <div className={`timeline-dot ${d.decision}`}>{icon}</div>
              <div className="timeline-card">
                <div className="timeline-date">
                  {new Date(d.decided_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                </div>
                <div className={`timeline-label ${d.decision}`}>{headline}</div>
                <div className="timeline-detail">{detail}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
