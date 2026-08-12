import { BODY, C, NUM } from "../theme.js";

export default function Bar({ label, value, max, unit, tone }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div>
      <div className="flex justify-between items-baseline">
        <span style={{ fontFamily: BODY, fontSize: 12, color: C.inkSoft }}>{label}</span>
        <span style={{ fontFamily: NUM, fontSize: 12, color: C.ink }}>{value}{unit}</span>
      </div>
      <div style={{ height: 5, background: C.line, borderRadius: 3, marginTop: 5 }}>
        <div style={{ height: "100%", width: `${pct}%`, background: tone, borderRadius: 3 }} />
      </div>
    </div>
  );
}
