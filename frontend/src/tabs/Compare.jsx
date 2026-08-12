import { BODY, C, DISPLAY } from "../theme.js";
import { usePair } from "../hooks/usePair.js";
import ParcelPlate from "../components/ParcelPlate.jsx";
import Bar from "../components/Bar.jsx";
import DriveRow from "../components/DriveRow.jsx";

export default function Compare({ rater, anchors }) {
  const { pair, loading, error, choose } = usePair(rater);

  if (loading) {
    return (
      <div className="py-24 text-center">
        <p style={{ fontFamily: BODY, color: C.inkSoft, fontSize: 16 }}>Loading...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-24 text-center">
        <p style={{ fontFamily: BODY, color: C.inkSoft, fontSize: 16, maxWidth: 420, margin: "0 auto" }}>
          Not enough rated listings yet to build a comparison. Rate a few more in Consider first.
        </p>
      </div>
    );
  }

  if (!pair) return null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 style={{ fontFamily: DISPLAY, fontSize: 34, fontWeight: 300, color: C.ink, lineHeight: 1.1 }}>
          If you could only walk one of these, which would it be?
        </h2>
        <p style={{ fontFamily: BODY, fontSize: 14, color: C.mist, marginTop: 8 }}>
          These two are close enough that the model can't call it, so your answer is worth several ordinary ones.
        </p>
      </div>
      <div className="grid gap-5" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(290px,1fr))" }}>
        {pair.map((l) => (
          <button key={l.id} onClick={() => choose(l.id)} className="text-left"
            style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 8, padding: 0, cursor: "pointer", overflow: "hidden" }}>
            <ParcelPlate listing={l} />
            <div style={{ padding: 20 }}>
              <div style={{ fontFamily: DISPLAY, fontSize: 26, fontWeight: 300, color: C.ink, lineHeight: 1.1 }}>
                {l.address}
              </div>
              <div style={{ fontFamily: BODY, fontSize: 13, color: C.inkSoft, marginTop: 6 }}>
                {l.archStyle || "Style unclassified"} · {l.yearBuilt ?? "?"} ·{" "}
                {l.price ? `$${(l.price / 1000).toFixed(0)}k` : "?"} · {l.lotAcres ?? "?"} ac
              </div>
              <div className="flex flex-col gap-3 mt-4">
                <Bar label="Canopy on the lot" value={l.parcelCanopy ?? 0} max={100} unit="%" tone={C.canopy} />
                <Bar label="Boundary protected" value={Math.round((l.protectedRatio ?? 0) * 100)} max={100} unit="%" tone={C.tide} />
              </div>
              <div className="mt-4">
                {Object.entries(l.drives).slice(0, 2).map(([label, mins]) => (
                  <DriveRow key={label} label={label} mins={mins} anchor={anchors.find((a) => a.label === label)} />
                ))}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
