import { useState } from "react";
import { BODY, C, DISPLAY } from "../theme.js";
import { useBatch } from "../hooks/useBatch.js";
import { useTags } from "../hooks/useTags.js";
import ParcelPlate from "../components/ParcelPlate.jsx";
import Figure from "../components/Figure.jsx";
import Bar from "../components/Bar.jsx";
import DriveRow from "../components/DriveRow.jsx";
import Card from "../components/Card.jsx";

export default function Consider({ rater, anchors }) {
  const { current: listing, remaining, done, loading, judge } = useBatch(rater);
  const { negTags, posTags } = useTags();

  const [verdict, setVerdict] = useState(null);
  const [picked, setPicked] = useState([]);
  const [anchorPick, setAnchorPick] = useState([]);

  const tags = verdict === "no" ? negTags : posTags;
  // tags come after the verdict -- snap judgment first, rationalize
  // second (UI_SPEC.md §6). This block only renders once `verdict` is set.
  const anchorTagOn = picked.some((c) => tags.find((t) => t.code === c)?.anchorAware);

  function toggle(code) {
    setPicked((p) => (p.includes(code) ? p.filter((c) => c !== code) : [...p, code]));
  }
  function toggleAnchor(id) {
    setAnchorPick((p) => (p.includes(id) ? p.filter((a) => a !== id) : [...p, id]));
  }
  async function commit() {
    await judge(verdict, picked, anchorPick);
    setVerdict(null); setPicked([]); setAnchorPick([]);
  }

  if (loading) {
    return (
      <div className="py-24 text-center">
        <p style={{ fontFamily: BODY, color: C.inkSoft, fontSize: 16 }}>Loading...</p>
      </div>
    );
  }

  if (!listing) {
    return (
      <div className="py-24 text-center">
        <div style={{ fontFamily: DISPLAY, fontSize: 40, color: C.ink, fontWeight: 300 }}>
          That's the batch.
        </div>
        <p style={{ fontFamily: BODY, color: C.inkSoft, marginTop: 10, fontSize: 16 }}>
          {done} homes considered. Open Patterns to see what it learned.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-7">
      <div className="flex justify-between items-baseline">
        <span style={{ fontFamily: BODY, fontSize: 12, color: C.mist }}>{listing.id}</span>
        <span style={{ fontFamily: BODY, fontSize: 12, color: C.mist }}>{remaining} to go</span>
      </div>

      <div>
        <h2 style={{ fontFamily: DISPLAY, fontSize: 42, fontWeight: 300, color: C.ink, lineHeight: 1.05, letterSpacing: "-0.01em" }}>
          {listing.address}
        </h2>
        <p style={{ fontFamily: BODY, fontSize: 15, color: C.inkSoft, marginTop: 8 }}>
          {listing.archStyle || "Style not yet classified"} · built {listing.yearBuilt ?? "unknown"} ·{" "}
          {listing.beds ?? "?"} bed, {listing.baths ?? "?"} bath ·{" "}
          {listing.sqft ? listing.sqft.toLocaleString() : "?"} sq ft
        </p>
      </div>

      <div className="grid gap-5" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))" }}>
        <Card pad={0}>
          <ParcelPlate listing={listing} />
        </Card>
        <div className="flex flex-col gap-4">
          <div style={{ borderRadius: 8, overflow: "hidden", border: `1px solid ${C.line}`, minHeight: 150 }}>
            <img
              src={`/api/listings/${listing.id}/location-map`}
              alt={`Map of the area around ${listing.address}`}
              style={{ width: "100%", height: "100%", display: "block", objectFit: "cover" }}
            />
          </div>
          <div className="grid gap-4" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Figure label="Asking" value={listing.price ? `$${(listing.price / 1000).toFixed(0)}k` : "?"} />
            <Figure label="Lot" value={listing.lotAcres != null ? `${listing.lotAcres} ac` : "?"} />
            <Figure label="Street" value={listing.isCulDeSac ? "Cul-de-sac" : (listing.roadClass || "Not yet classified")} />
            <Figure label="Flood zone" value={listing.floodZone || "?"} />
          </div>
        </div>
      </div>

      <div className="grid gap-6" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))" }}>
        <Card>
          <div style={{ fontFamily: DISPLAY, fontSize: 18, color: C.ink, marginBottom: 14, fontWeight: 400 }}>
            The land
          </div>
          <div className="flex flex-col gap-4">
            <Bar label="Canopy on the lot" value={listing.parcelCanopy ?? 0} max={100} unit="%" tone={C.canopy} />
            <Bar label="Canopy on the street" value={listing.neighborhoodCanopy ?? 0} max={100} unit="%" tone={C.canopy} />
            <Bar label="Boundary that's protected" value={Math.round((listing.protectedRatio ?? 0) * 100)} max={100} unit="%" tone={C.tide} />
            <Bar label="Open space behind" value={listing.rearOpenFt ?? 0} max={400} unit=" ft" tone={C.marsh} />
          </div>
        </Card>
        <Card>
          <div style={{ fontFamily: DISPLAY, fontSize: 18, color: C.ink, marginBottom: 6, fontWeight: 400 }}>
            Getting places
          </div>
          {Object.keys(listing.drives).length === 0 ? (
            <p style={{ fontFamily: BODY, fontSize: 13, color: C.mist }}>
              Add places you care about in the Places tab to see drive times here.
            </p>
          ) : (
            Object.entries(listing.drives).map(([label, mins]) => (
              <DriveRow key={label} label={label} mins={mins} anchor={anchors.find((a) => a.label === label)} />
            ))
          )}
        </Card>
      </div>

      {!verdict ? (
        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))" }}>
          <button onClick={() => setVerdict("no")} className="py-4"
            style={{ fontFamily: DISPLAY, fontSize: 20, fontWeight: 400, color: C.clay, background: "transparent", border: `1px solid ${C.clay}`, borderRadius: 6, cursor: "pointer" }}>
            Not for us
          </button>
          <button onClick={() => judge("maybe", [], [])} className="py-4"
            style={{ fontFamily: DISPLAY, fontSize: 20, fontWeight: 400, color: C.inkSoft, background: "transparent", border: `1px solid ${C.line}`, borderRadius: 6, cursor: "pointer" }}>
            Maybe
          </button>
          <button onClick={() => setVerdict("yes")} className="py-4"
            style={{ fontFamily: DISPLAY, fontSize: 20, fontWeight: 400, color: C.card, background: C.canopyDeep, border: `1px solid ${C.canopyDeep}`, borderRadius: 6, cursor: "pointer" }}>
            Yes, this one
          </button>
        </div>
      ) : (
        <Card>
          <div style={{ fontFamily: DISPLAY, fontSize: 22, color: C.ink, fontWeight: 300, marginBottom: 14 }}>
            {verdict === "no" ? "What ruled it out?" : "What made it work?"}
          </div>
          <div className="flex flex-wrap gap-2">
            {tags.map((t) => {
              const on = picked.includes(t.code);
              return (
                <button key={t.code} onClick={() => toggle(t.code)}
                  style={{
                    fontFamily: BODY, fontSize: 14, padding: "8px 14px", borderRadius: 20, cursor: "pointer",
                    color: on ? C.card : C.ink,
                    background: on ? (verdict === "no" ? C.clay : C.canopyDeep) : "transparent",
                    border: `1px solid ${on ? "transparent" : C.line}`,
                  }}>
                  {t.label}
                </button>
              );
            })}
          </div>

          {anchorTagOn && (
            <div className="mt-5 pt-4" style={{ borderTop: `1px solid ${C.line}` }}>
              <div style={{ fontFamily: BODY, fontSize: 13, color: C.inkSoft, marginBottom: 10 }}>
                Which places were you thinking of? Optional, but it tells the model which drives actually matter.
              </div>
              <div className="flex flex-wrap gap-2">
                {anchors.map((a) => {
                  const on = anchorPick.includes(a.id);
                  return (
                    <button key={a.id} onClick={() => toggleAnchor(a.id)}
                      style={{
                        fontFamily: BODY, fontSize: 13, padding: "6px 12px", borderRadius: 20, cursor: "pointer",
                        color: on ? C.card : C.inkSoft,
                        background: on ? C.tide : "transparent",
                        border: `1px solid ${on ? "transparent" : C.line}`,
                      }}>
                      {a.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-3 mt-6">
            <button onClick={commit} className="py-3 px-7"
              style={{ fontFamily: DISPLAY, fontSize: 18, background: C.ink, color: C.card, border: "none", borderRadius: 6, cursor: "pointer" }}>
              Save and continue
            </button>
            <button onClick={() => { setVerdict(null); setPicked([]); setAnchorPick([]); }} className="py-3 px-5"
              style={{ fontFamily: BODY, fontSize: 14, color: C.inkSoft, background: "transparent", border: `1px solid ${C.line}`, borderRadius: 6, cursor: "pointer" }}>
              Back
            </button>
          </div>
        </Card>
      )}
    </div>
  );
}
