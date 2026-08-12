import { useState } from "react";
import { BODY, C, DISPLAY } from "./theme.js";
import { useAnchors } from "./hooks/useAnchors.js";
import Consider from "./tabs/Consider.jsx";
import Compare from "./tabs/Compare.jsx";
import Places from "./tabs/Places.jsx";
import Patterns from "./tabs/Patterns.jsx";

const RATERS = [
  { k: "zach", n: "Zach" },
  { k: "andrea", n: "Andrea" },
];

const TABS = [
  { k: "consider", label: "Consider" },
  { k: "compare", label: "Compare" },
  { k: "places", label: "Places" },
  { k: "patterns", label: "Patterns" },
];

export default function App() {
  const [rater, setRater] = useState("zach");
  const [tab, setTab] = useState("consider");
  const { anchors } = useAnchors();

  return (
    <div style={{ background: C.paper, minHeight: "100vh" }}>
      <div className="mx-auto px-6 py-8" style={{ maxWidth: 900 }}>
        <header className="flex flex-wrap justify-between items-center gap-4 pb-6">
          <div>
            <div style={{ fontFamily: DISPLAY, fontSize: 30, fontWeight: 300, color: C.ink }}>
              Canopy
            </div>
            <div style={{ fontFamily: BODY, fontSize: 12, color: C.mist, marginTop: 1 }}>
              Finding your place in Wilmington
            </div>
          </div>
          <div className="flex gap-2">
            {RATERS.map((r) => (
              <button key={r.k} onClick={() => setRater(r.k)} className="px-4 py-2"
                style={{
                  fontFamily: BODY, fontSize: 13, cursor: "pointer", borderRadius: 20,
                  background: rater === r.k ? C.ink : "transparent",
                  color: rater === r.k ? C.card : C.inkSoft,
                  border: `1px solid ${rater === r.k ? C.ink : C.line}`,
                }}>
                {r.n}
              </button>
            ))}
          </div>
        </header>

        <nav className="flex flex-wrap gap-6 pb-8" style={{ borderBottom: `1px solid ${C.line}` }}>
          {TABS.map((t) => (
            <button key={t.k} onClick={() => setTab(t.k)}
              style={{
                fontFamily: BODY, fontSize: 15, background: "none", border: "none", cursor: "pointer",
                padding: "0 0 6px", marginBottom: -1,
                color: tab === t.k ? C.ink : C.mist,
                borderBottom: `2px solid ${tab === t.k ? C.canopyDeep : "transparent"}`,
              }}>
              {t.label}
            </button>
          ))}
        </nav>

        {/* rater switch is global and always visible -- no shared
            judgments, ever (UI_SPEC.md §6). Re-mounting each tab on
            rater change (via key) forces a clean refetch instead of
            risking stale per-rater state leaking across the switch. */}
        <main className="py-8 pb-20">
          {tab === "consider" && <Consider key={`consider-${rater}`} rater={rater} anchors={anchors} />}
          {tab === "compare" && <Compare key={`compare-${rater}`} rater={rater} anchors={anchors} />}
          {tab === "places" && <Places rater={rater} />}
          {tab === "patterns" && <Patterns key={`patterns-${rater}`} rater={rater} />}
        </main>

        <footer className="pt-5" style={{ borderTop: `1px solid ${C.line}`, fontFamily: BODY, fontSize: 12, color: C.mist }}>
          Canopy · Wilmington, NC
        </footer>
      </div>
    </div>
  );
}
