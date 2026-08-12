import { C } from "../theme.js";

export default function Card({ children, pad = 24 }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 8, padding: pad }}>
      {children}
    </div>
  );
}
