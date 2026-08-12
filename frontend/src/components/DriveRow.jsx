import { BODY, C, NUM } from "../theme.js";

export default function DriveRow({ label, mins, anchor }) {
  const state = !anchor ? "ok" : mins <= anchor.ideal ? "ideal" : mins <= anchor.limit ? "ok" : "over";
  const tone = state === "ideal" ? C.canopy : state === "ok" ? C.marsh : C.clay;
  const note = state === "ideal" ? "within ideal" : state === "ok" ? "workable" : "past your limit";
  return (
    <div className="flex items-baseline justify-between py-2 gap-3" style={{ borderBottom: `1px solid ${C.line}` }}>
      <span style={{ fontFamily: BODY, fontSize: 14, color: C.ink }}>{label}</span>
      <span className="flex items-baseline gap-2">
        <span style={{ fontFamily: BODY, fontSize: 11, color: tone }}>{note}</span>
        <span style={{ fontFamily: NUM, fontSize: 14, color: C.ink }}>{mins} min</span>
      </span>
    </div>
  );
}
