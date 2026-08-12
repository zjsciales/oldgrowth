import { useEffect, useState } from "react";
import { BODY, C, DISPLAY } from "../theme.js";
import { getWeights } from "../api.js";
import Card from "../components/Card.jsx";

const FEATURE_LABELS = {
  parcel_canopy_pct: "Canopy on the lot",
  neighborhood_canopy_pct: "Canopy on the street",
  protected_perimeter_ratio: "Protected perimeter",
  rear_open_distance_ft: "Open space behind",
  fronting_road_class: "Road type",
  arch_style: "Architecture",
  lot_acreage: "Lot size",
  flood_zone: "Flood zone",
  price_per_sqft: "Price per sq ft",
  year_built: "Year built",
  abuts_water: "Water adjacency",
  min_drive_beach: "Drive to the beach",
  min_drive_grocery: "Drive to groceries",
  min_drive_work: "Drive to work",
  min_drive_school: "Drive to school",
  mean_drive_social: "Drive to people",
};

const KIND_LABELS = {
  hygiene: "Only matters when it's bad",
  delighter: "Wins you over",
  linear: "Cuts both ways",
};

export default function Patterns({ rater }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getWeights(rater)
      .then((d) => { if (!cancelled) setData(d); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [rater]);

  const rows = data
    ? Object.entries(data.tagStats || {})
        .map(([f, stats]) => ({ f, ...stats }))
        .sort((a, b) => b.n - a.n)
    : [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 style={{ fontFamily: DISPLAY, fontSize: 34, fontWeight: 300, color: C.ink, lineHeight: 1.1 }}>
          What you've told it so far
        </h2>
        <p style={{ fontFamily: BODY, fontSize: 15, color: C.inkSoft, marginTop: 8, maxWidth: 560, lineHeight: 1.6 }}>
          {data?.status === "ok"
            ? `${data.n_pairs} pairs learned from so far${
                data.holdoutAccuracy != null ? `, ${Math.round(data.holdoutAccuracy * 100)}% holdout accuracy` : ""
              }.`
            : "Still calibrating -- rate a few dozen homes before trusting the ranking."}
        </p>
      </div>

      {loading ? (
        <Card pad={48}>
          <p style={{ fontFamily: BODY, color: C.inkSoft, textAlign: "center", fontSize: 15 }}>Loading...</p>
        </Card>
      ) : rows.length === 0 ? (
        <Card pad={48}>
          <p style={{ fontFamily: BODY, color: C.inkSoft, textAlign: "center", fontSize: 15 }}>
            Rate a few homes and say why. Your patterns show up here.
          </p>
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          {rows.map((r) => {
            const kindLabel = r.n < 10 ? "Still learning" : KIND_LABELS[r.kind] || "Cuts both ways";
            return (
              <Card key={r.f} pad={18}>
                <div className="flex justify-between items-baseline mb-3 gap-3 flex-wrap">
                  <span style={{ fontFamily: DISPLAY, fontSize: 20, fontWeight: 400, color: C.ink }}>
                    {FEATURE_LABELS[r.f] || r.f}
                  </span>
                  <span style={{ fontFamily: BODY, fontSize: 12, color: kindLabel === "Still learning" ? C.mist : C.tide }}>
                    {kindLabel}
                  </span>
                </div>
                <div className="flex items-center" style={{ height: 10 }}>
                  <div style={{ flex: 1, display: "flex", justifyContent: "flex-end", height: "100%", background: C.line, borderRadius: "5px 0 0 5px" }}>
                    <div style={{ width: `${(r.blame / Math.max(r.n, 1)) * 100}%`, background: C.clay, height: "100%", borderRadius: "5px 0 0 5px" }} />
                  </div>
                  <div style={{ width: 2, height: 16, background: C.ink, opacity: 0.3 }} />
                  <div style={{ flex: 1, height: "100%", background: C.line, borderRadius: "0 5px 5px 0" }}>
                    <div style={{ width: `${(r.credit / Math.max(r.n, 1)) * 100}%`, background: C.canopy, height: "100%", borderRadius: "0 5px 5px 0" }} />
                  </div>
                </div>
                <div className="flex justify-between mt-2" style={{ fontFamily: BODY, fontSize: 12, color: C.mist }}>
                  <span>{r.blame} ruled out</span>
                  <span>{r.credit} won you over</span>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
