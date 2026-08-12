import { C, EDGE_META, NUM } from "../theme.js";

/* ============================================================
   Parcel plate -- the signature element. Moved verbatim from
   docs/RatingUI.jsx (pure function of listing/w/h props only).

   All randomness is seeded from the listing ID, so a given lot renders
   identically in Consider and in Compare -- not cosmetic, inconsistent
   rendering between views would be an uncontrolled variable inside the
   pairwise training data (UI_SPEC.md §2.3). SVG <defs> IDs are
   namespaced per listing so two plates can render side by side in
   Compare without colliding.
   ============================================================ */

export default function ParcelPlate({ listing, w = 420, h = 360 }) {
  const uid = `p${listing.id.replace(/[^a-zA-Z0-9]/g, "")}`;
  const band = 46;
  const lx = band, ly = band, lw = w - band * 2, lh = h - band * 2;

  const seed = listing.id.split("").reduce((a, c) => a + c.charCodeAt(0), 7);
  const mk = (s0) => { let s = s0; return () => ((s = (s * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff); };

  /* Canopy coverage: for randomly placed crowns of area a over region A,
     expected coverage c = 1 - exp(-n*a/A)  →  n = -ln(1-c) * A/a.
     Self-corrects for overlap, so 74% actually reads as 74%. */
  const crowns = (cov, region, radius, rnd) => {
    const c = Math.min(0.95, Math.max(0, cov / 100));
    const a = Math.PI * radius * radius;
    const A = region.w * region.h;
    const n = Math.max(0, Math.ceil((-Math.log(1 - c) * A) / a));
    return Array.from({ length: n }, () => ({
      x: region.x + rnd() * region.w,
      y: region.y + rnd() * region.h,
      r: radius * (0.72 + rnd() * 0.56),
    }));
  };

  const rnd = mk(seed);
  const lotCrowns = crowns(listing.parcelCanopy, { x: lx, y: ly, w: lw, h: lh }, lw * 0.085, rnd);
  const hoodCrowns = crowns(
    Math.min(listing.neighborhoodCanopy * 0.55, 55),
    { x: 0, y: 0, w, h }, lw * 0.07, mk(seed + 31)
  );

  const houseW = lw * 0.34, houseH = lh * 0.24;
  const houseX = lx + lw / 2 - houseW / 2, houseY = ly + lh - houseH - lh * 0.12;

  const edges = {
    n: { x: lx, y: 0, w: lw, h: band },
    s: { x: lx, y: h - band, w: lw, h: band },
    w: { x: 0, y: ly, w: band, h: lh },
    e: { x: w - band, y: ly, w: band, h: lh },
  };

  function EdgeBand({ side, type }) {
    const r = edges[side];
    const horiz = side === "n" || side === "s";
    const er = mk(seed + side.charCodeAt(0) * 17);

    if (type === "water") {
      const lines = [];
      const count = horiz ? 5 : 6;
      for (let i = 1; i <= count; i++) {
        const t = i / (count + 1);
        if (horiz) {
          const y = r.y + t * r.h;
          let d = `M ${r.x} ${y}`;
          for (let x = r.x; x < r.x + r.w; x += 22) d += ` q 11 ${er() > 0.5 ? -4 : 4} 22 0`;
          lines.push(d);
        } else {
          const x = r.x + t * r.w;
          let d = `M ${x} ${r.y}`;
          for (let y = r.y; y < r.y + r.h; y += 22) d += ` q ${er() > 0.5 ? -4 : 4} 11 0 22`;
          lines.push(d);
        }
      }
      return (
        <g>
          <rect x={r.x} y={r.y} width={r.w} height={r.h} fill={C.tidePale} />
          {lines.map((d, i) => (
            <path key={i} d={d} fill="none" stroke={C.tide} strokeWidth="1.6" opacity="0.65" strokeLinecap="round" />
          ))}
        </g>
      );
    }

    if (type === "park" || type === "conservation") {
      const cr = crowns(78, r, Math.min(r.w, r.h) * 0.3, er);
      return (
        <g>
          <rect x={r.x} y={r.y} width={r.w} height={r.h} fill={C.canopyPale} />
          {cr.map((c, i) => <circle key={i} cx={c.x} cy={c.y} r={c.r} fill={C.canopyDeep} opacity="0.45" />)}
        </g>
      );
    }

    if (type === "marsh") {
      const tufts = [];
      const step = 13;
      if (horiz) {
        for (let x = r.x + 6; x < r.x + r.w; x += step) {
          const y = r.y + r.h * (0.35 + er() * 0.4), len = 9 + er() * 8;
          tufts.push(`M ${x} ${y} l -3 ${-len} M ${x} ${y} l 0 ${-len - 3} M ${x} ${y} l 3 ${-len}`);
        }
      } else {
        for (let y = r.y + 6; y < r.y + r.h; y += step) {
          const x = r.x + r.w * (0.35 + er() * 0.4), len = 9 + er() * 8;
          tufts.push(`M ${x} ${y} l ${-len} -3 M ${x} ${y} l ${-len - 3} 0 M ${x} ${y} l ${-len} 3`);
        }
      }
      return (
        <g>
          <rect x={r.x} y={r.y} width={r.w} height={r.h} fill={C.marshPale} />
          {tufts.map((d, i) => (
            <path key={i} d={d} fill="none" stroke={C.marsh} strokeWidth="1.3" opacity="0.8" strokeLinecap="round" />
          ))}
        </g>
      );
    }

    if (type === "road") {
      const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
      return (
        <g>
          <rect x={r.x} y={r.y} width={r.w} height={r.h} fill="#E4E7E4" />
          <line
            x1={horiz ? r.x : cx} y1={horiz ? cy : r.y}
            x2={horiz ? r.x + r.w : cx} y2={horiz ? cy : r.y + r.h}
            stroke={C.slate} strokeWidth="1.4" strokeDasharray="9 9" opacity="0.85" />
        </g>
      );
    }

    // buildable -- hatched ground with building footprints, reads as a threat
    const foots = [];
    for (let i = 0; i < 3; i++) {
      const t = (i + 0.5) / 3;
      const bw = horiz ? r.w * 0.16 : r.w * 0.44;
      const bh = horiz ? r.h * 0.4 : r.h * 0.16;
      foots.push({
        x: horiz ? r.x + t * r.w - bw / 2 : r.x + r.w * 0.28,
        y: horiz ? r.y + r.h * 0.28 : r.y + t * r.h - bh / 2,
        w: bw, h: bh,
      });
    }
    return (
      <g>
        <rect x={r.x} y={r.y} width={r.w} height={r.h} fill={`url(#${uid}-hatch)`} />
        {foots.map((f, i) => (
          <rect key={i} x={f.x} y={f.y} width={f.w} height={f.h}
            fill="none" stroke={C.slate} strokeWidth="1.2" opacity="0.75" />
        ))}
      </g>
    );
  }

  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block", borderRadius: 6 }}
      role="img"
      aria-label={`Site plan for ${listing.address}: ${listing.parcelCanopy} percent tree canopy on the lot, ${Math.round(listing.protectedRatio * 100)} percent of the boundary abuts protected land`}>
      <defs>
        <pattern id={`${uid}-hatch`} width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
          <rect width="7" height="7" fill="#EDEFEB" />
          <line x1="0" y1="0" x2="0" y2="7" stroke={C.slate} strokeWidth="1" opacity="0.4" />
        </pattern>
        <clipPath id={`${uid}-lot`}>
          <rect x={lx} y={ly} width={lw} height={lh} rx="3" />
        </clipPath>
        <filter id={`${uid}-soft`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="2.2" />
        </filter>
      </defs>

      <rect width={w} height={h} fill="#EFF2ED" />

      <g opacity="0.4">
        {hoodCrowns.map((c, i) => <circle key={i} cx={c.x} cy={c.y} r={c.r} fill={C.canopy} opacity="0.35" />)}
      </g>

      {Object.entries(listing.edges).map(([side, type]) => (
        <EdgeBand key={side} side={side} type={type} />
      ))}

      <rect x={lx} y={ly} width={lw} height={lh} rx="3" fill="#F4F7F1" />

      <g clipPath={`url(#${uid}-lot)`}>
        <g filter={`url(#${uid}-soft)`} opacity="0.62">
          {lotCrowns.map((c, i) => <circle key={`b${i}`} cx={c.x} cy={c.y} r={c.r * 1.15} fill={C.canopy} />)}
        </g>
        <g opacity="0.5">
          {lotCrowns.map((c, i) => <circle key={`d${i}`} cx={c.x} cy={c.y} r={c.r * 0.55} fill={C.canopyDeep} />)}
        </g>
      </g>

      <rect x={houseX} y={houseY} width={houseW} height={houseH} rx="2"
        fill={C.card} stroke={C.ink} strokeWidth="1.3" />
      <line x1={houseX} y1={houseY + houseH * 0.42} x2={houseX + houseW} y2={houseY + houseH * 0.42}
        stroke={C.ink} strokeWidth="0.9" opacity="0.45" />

      <rect x={lx} y={ly} width={lw} height={lh} rx="3"
        fill="none" stroke={C.ink} strokeWidth="1.1" opacity="0.5" strokeDasharray="3 3" />

      {Object.entries(listing.edges).map(([side, type]) => {
        const r = edges[side];
        const horiz = side === "n" || side === "s";
        return (
          <text key={side}
            x={horiz ? r.x + 5 : r.x + r.w / 2}
            y={horiz ? r.y + (side === "n" ? 13 : r.h - 5) : r.y + 12}
            fill={C.inkSoft} fontFamily={NUM} fontSize="8.5" opacity="0.85"
            textAnchor={horiz ? "start" : "middle"}>
            {EDGE_META[type].label}
          </text>
        );
      })}
    </svg>
  );
}
