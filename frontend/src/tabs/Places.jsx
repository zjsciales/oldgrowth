import { useState } from "react";
import { BODY, C, DISPLAY, NUM } from "../theme.js";
import { useAnchors } from "../hooks/useAnchors.js";
import Card from "../components/Card.jsx";

const CATEGORIES = ["beach", "grocery", "social", "work", "school"];
const CATEGORY_LABELS = { beach: "Beach", grocery: "Errands", social: "People", work: "Work", school: "School" };

export default function Places({ rater }) {
  const { anchors, loading, add, update, remove } = useAnchors();
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState("social");
  const [saving, setSaving] = useState(false);
  const [addError, setAddError] = useState(null);

  async function handleAdd() {
    if (!label.trim()) return;
    setSaving(true);
    setAddError(null);
    try {
      // one text field, geocoded server-side (canopy/clients/mapbox.py) --
      // no separate lat/lon inputs needed
      await add({ label: label.trim(), category, created_by: rater, address: label.trim() });
      setLabel("");
    } catch (err) {
      setAddError(err.message);
    } finally {
      setSaving(false);
    }
  }

  function handleUpdate(id, key, val) {
    update(id, { [key]: Math.max(1, Number(val) || 1) });
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 style={{ fontFamily: DISPLAY, fontSize: 34, fontWeight: 300, color: C.ink, lineHeight: 1.1 }}>
          The places you actually go
        </h2>
        <p style={{ fontFamily: BODY, fontSize: 15, color: C.inkSoft, marginTop: 8, maxWidth: 560, lineHeight: 1.6 }}>
          Every home gets scored on drive time to each of these. One shared list, so you'll both see the same
          places and either of you can add one. The two numbers mark where a drive stops feeling easy, and
          where it stops being worth it.
        </p>
      </div>

      <Card>
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex-1" style={{ minWidth: 200 }}>
            <label style={{ fontFamily: BODY, fontSize: 12, color: C.mist, display: "block", marginBottom: 6 }}>
              Address or place name
            </label>
            <input value={label} onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Wrightsville Beach public access"
              style={{ width: "100%", fontFamily: BODY, fontSize: 14, padding: "10px 12px", borderRadius: 6, border: `1px solid ${C.line}`, background: C.paper, color: C.ink }} />
          </div>
          <div>
            <label style={{ fontFamily: BODY, fontSize: 12, color: C.mist, display: "block", marginBottom: 6 }}>
              Kind
            </label>
            <select value={category} onChange={(e) => setCategory(e.target.value)}
              style={{ fontFamily: BODY, fontSize: 14, padding: "10px 12px", borderRadius: 6, border: `1px solid ${C.line}`, background: C.paper, color: C.ink }}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
            </select>
          </div>
          <button onClick={handleAdd} disabled={saving} className="py-3 px-6"
            style={{ fontFamily: DISPLAY, fontSize: 16, background: C.ink, color: C.card, border: "none", borderRadius: 6, cursor: saving ? "default" : "pointer", opacity: saving ? 0.6 : 1 }}>
            {saving ? "Adding..." : "Add place"}
          </button>
        </div>
        {addError && (
          <p style={{ fontFamily: BODY, fontSize: 13, color: C.clay, marginTop: 10 }}>{addError}</p>
        )}
      </Card>

      {!loading && anchors.length === 0 && (
        <p style={{ fontFamily: BODY, fontSize: 14, color: C.mist }}>No places yet -- add the first one above.</p>
      )}

      <div className="flex flex-col gap-3">
        {anchors.map((a) => (
          <Card key={a.id} pad={18}>
            <div className="flex flex-wrap gap-4 items-center justify-between">
              <div style={{ minWidth: 170 }}>
                <div style={{ fontFamily: DISPLAY, fontSize: 20, fontWeight: 400, color: C.ink }}>{a.label}</div>
                <div style={{ fontFamily: BODY, fontSize: 12, color: C.mist }}>
                  {CATEGORY_LABELS[a.category] || a.category}
                </div>
              </div>
              <div className="flex flex-wrap gap-5 items-end">
                {[
                  { k: "ideal", label: "Easy up to", tone: C.canopy },
                  { k: "limit", label: "Too far past", tone: C.clay },
                ].map((f) => (
                  <div key={f.k}>
                    <label style={{ fontFamily: BODY, fontSize: 11, color: C.mist, display: "block", marginBottom: 4 }}>
                      {f.label}
                    </label>
                    <div className="flex items-baseline gap-1">
                      <input type="number" value={a[f.k]} onChange={(e) => handleUpdate(a.id, f.k, e.target.value)}
                        style={{ width: 58, fontFamily: NUM, fontSize: 15, padding: "6px 8px", borderRadius: 6, border: `1px solid ${C.line}`, background: C.paper, color: f.tone }} />
                      <span style={{ fontFamily: BODY, fontSize: 12, color: C.mist }}>min</span>
                    </div>
                  </div>
                ))}
                <button onClick={() => remove(a.id)}
                  style={{ fontFamily: BODY, fontSize: 12, color: C.mist, background: "transparent", border: "none", cursor: "pointer", padding: "8px 4px" }}>
                  Remove
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <p style={{ fontFamily: BODY, fontSize: 13, color: C.mist, maxWidth: 560, lineHeight: 1.6 }}>
        These numbers seed the model. They're a starting guess, not a rule: once you've tagged enough homes as
        well or badly placed, it learns your real tolerances and quietly replaces them.
      </p>
    </div>
  );
}
