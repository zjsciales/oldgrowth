import { BODY, C, DISPLAY } from "../theme.js";

export default function Figure({ label, value, sub }) {
  return (
    <div>
      <div style={{ fontFamily: BODY, fontSize: 11, color: C.mist, letterSpacing: "0.04em" }}>{label}</div>
      <div style={{ fontFamily: DISPLAY, fontSize: 26, color: C.ink, fontWeight: 400, lineHeight: 1.2, marginTop: 2 }}>
        {value}
      </div>
      {sub && <div style={{ fontFamily: BODY, fontSize: 11, color: C.mist }}>{sub}</div>}
    </div>
  );
}
