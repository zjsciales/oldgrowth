import { useState, useMemo } from "react";

/* ============================================================
   Canopy — Rating UI prototype v2
   Mock data only. See UI_SPEC.md for the API contract.
   ============================================================ */

const C = {
  paper: "#F6F8F4",
  card: "#FDFCF8",
  ink: "#1B3A31",
  inkSoft: "#4A6B5F",
  mist: "#8FA79B",
  line: "#DFE7DE",
  canopy: "#6FA368",
  canopyDeep: "#3E6B45",
  canopyPale: "#C7DCBE",
  tide: "#5B9AA8",
  tidePale: "#BEDBE0",
  marsh: "#C3A45C",
  marshPale: "#E8DBB6",
  clay: "#B5705A",
  slate: "#9AA5A0",
};

const DISPLAY = "'Fraunces', Georgia, serif";
const BODY = "'Karla', system-ui, sans-serif";
const NUM = "'IBM Plex Mono', ui-monospace, monospace";

const EDGE_META = {
  water: { label: "Open water", color: C.tide },
  marsh: { label: "Marsh", color: C.marsh },
  park: { label: "Park", color: C.canopyDeep },
  conservation: { label: "Conservation land", color: C.canopyDeep },
  buildable: { label: "Buildable lot", color: C.slate },
  road: { label: "Road", color: C.slate },
};

/* ---------- Mock data ---------- */

const MOCK_LISTINGS = [
  { id: "L-1042", address: "418 Wrenwood Ct", price: 685000, sqft: 2410, beds: 4, baths: 3,
    yearBuilt: 1968, lotAcres: 0.61, parcelCanopy: 74, neighborhoodCanopy: 68,
    protectedRatio: 0.41, roadClass: "Quiet residential", isCulDeSac: true, floodZone: "X",
    archStyle: "Ranch", dom: 12, rearOpenFt: 210,
    drives: { "Wrightsville Beach": 14, "Harris Teeter, Oleander": 7, "The Robertsons": 19 },
    edges: { n: "marsh", e: "buildable", s: "road", w: "buildable" } },

  { id: "L-1088", address: "2210 Ivyhurst Rd", price: 749000, sqft: 2860, beds: 4, baths: 3,
    yearBuilt: 1952, lotAcres: 0.48, parcelCanopy: 81, neighborhoodCanopy: 79,
    protectedRatio: 0.12, roadClass: "Quiet residential", isCulDeSac: false, floodZone: "X",
    archStyle: "Colonial Revival", dom: 34, rearOpenFt: 95,
    drives: { "Wrightsville Beach": 21, "Harris Teeter, Oleander": 5, "The Robertsons": 11 },
    edges: { n: "buildable", e: "buildable", s: "road", w: "park" } },

  { id: "L-1113", address: "77 Sedgefield Loop", price: 612000, sqft: 2180, beds: 3, baths: 2,
    yearBuilt: 2016, lotAcres: 0.29, parcelCanopy: 22, neighborhoodCanopy: 31,
    protectedRatio: 0.0, roadClass: "Collector", isCulDeSac: false, floodZone: "X",
    archStyle: "New Traditional", dom: 6, rearOpenFt: 60,
    drives: { "Wrightsville Beach": 9, "Harris Teeter, Oleander": 4, "The Robertsons": 26 },
    edges: { n: "buildable", e: "buildable", s: "road", w: "buildable" } },

  { id: "L-1150", address: "905 Heron Bluff Way", price: 824000, sqft: 3040, beds: 4, baths: 4,
    yearBuilt: 1994, lotAcres: 0.88, parcelCanopy: 58, neighborhoodCanopy: 61,
    protectedRatio: 0.63, roadClass: "Quiet residential", isCulDeSac: true, floodZone: "AE",
    archStyle: "Coastal Contemporary", dom: 48, rearOpenFt: 340,
    drives: { "Wrightsville Beach": 11, "Harris Teeter, Oleander": 12, "The Robertsons": 22 },
    edges: { n: "water", e: "marsh", s: "road", w: "buildable" } },

  { id: "L-1177", address: "1436 Old Mill Rd", price: 559000, sqft: 1980, beds: 3, baths: 2,
    yearBuilt: 1941, lotAcres: 0.71, parcelCanopy: 69, neighborhoodCanopy: 84,
    protectedRatio: 0.24, roadClass: "Busy through road", isCulDeSac: false, floodZone: "X",
    archStyle: "Craftsman", dom: 71, rearOpenFt: 180,
    drives: { "Wrightsville Beach": 24, "Harris Teeter, Oleander": 3, "The Robertsons": 8 },
    edges: { n: "conservation", e: "buildable", s: "road", w: "buildable" } },

  { id: "L-1205", address: "63 Tidewater Reach", price: 910000, sqft: 3320, beds: 5, baths: 4,
    yearBuilt: 2004, lotAcres: 0.52, parcelCanopy: 34, neighborhoodCanopy: 29,
    protectedRatio: 0.48, roadClass: "Quiet residential", isCulDeSac: false, floodZone: "VE",
    archStyle: "Coastal Contemporary", dom: 19, rearOpenFt: 150,
    drives: { "Wrightsville Beach": 4, "Harris Teeter, Oleander": 14, "The Robertsons": 31 },
    edges: { n: "water", e: "water", s: "road", w: "buildable" } },

  { id: "L-1233", address: "8 Cypress Hollow", price: 645000, sqft: 2295, beds: 3, baths: 3,
    yearBuilt: 1974, lotAcres: 1.12, parcelCanopy: 88, neighborhoodCanopy: 72,
    protectedRatio: 0.55, roadClass: "Quiet residential", isCulDeSac: true, floodZone: "X",
    archStyle: "Ranch", dom: 3, rearOpenFt: 400,
    drives: { "Wrightsville Beach": 27, "Harris Teeter, Oleander": 11, "The Robertsons": 16 },
    edges: { n: "conservation", e: "marsh", s: "road", w: "buildable" } },

  { id: "L-1260", address: "5502 Market Crossing", price: 498000, sqft: 2040, beds: 3, baths: 2,
    yearBuilt: 1988, lotAcres: 0.26, parcelCanopy: 41, neighborhoodCanopy: 38,
    protectedRatio: 0.0, roadClass: "Busy through road", isCulDeSac: false, floodZone: "X",
    archStyle: "Ranch", dom: 27, rearOpenFt: 55,
    drives: { "Wrightsville Beach": 18, "Harris Teeter, Oleander": 2, "The Robertsons": 13 },
    edges: { n: "buildable", e: "buildable", s: "road", w: "buildable" } },
];

const DEFAULT_ANCHORS = [
  { id: 1, label: "Wrightsville Beach", category: "Beach", ideal: 15, limit: 25 },
  { id: 2, label: "Harris Teeter, Oleander", category: "Errands", ideal: 8, limit: 15 },
  { id: 3, label: "The Robertsons", category: "People", ideal: 15, limit: 30 },
];

/* ---------- Tags ---------- */

const NEG_TAGS = [
  { code: "road_too_busy", label: "Too close to a busy road", features: ["fronting_road_class"] },
  { code: "lot_too_open", label: "Lot too open", features: ["parcel_canopy_pct"] },
  { code: "street_too_bare", label: "Street lacks canopy", features: ["neighborhood_canopy_pct"] },
  { code: "backs_to_buildable", label: "Someone can build behind it", features: ["protected_perimeter_ratio"] },
  { code: "not_private", label: "Doesn't feel private", features: ["rear_open_distance_ft"] },
  { code: "wrong_architecture", label: "Wrong style", features: ["arch_style"] },
  { code: "too_far", label: "Too far from where we go", features: ["anchor_drive_times"], anchorAware: true },
  { code: "flood_risk", label: "Flood exposure", features: ["flood_zone"] },
  { code: "lot_too_small", label: "Lot too small", features: ["lot_acreage"] },
  { code: "overpriced", label: "Not worth the price", features: ["price_per_sqft"] },
  { code: "other_no", label: "Something else", features: [] },
];

const POS_TAGS = [
  { code: "abuts_protected", label: "Abuts protected land", features: ["protected_perimeter_ratio"] },
  { code: "feels_private", label: "Feels private", features: ["rear_open_distance_ft"] },
  { code: "mature_canopy", label: "Beautiful trees on the lot", features: ["parcel_canopy_pct"] },
  { code: "wooded_street", label: "Whole street is wooded", features: ["neighborhood_canopy_pct"] },
  { code: "quiet_street", label: "Quiet street", features: ["fronting_road_class"] },
  { code: "water_adjacency", label: "Water or marsh", features: ["abuts_water"] },
  { code: "love_architecture", label: "Love the style", features: ["arch_style"] },
  { code: "period_character", label: "Real character", features: ["year_built"] },
  { code: "big_lot", label: "Great lot size", features: ["lot_acreage"] },
  { code: "well_placed", label: "Well placed for us", features: ["anchor_drive_times"], anchorAware: true },
  { code: "good_value", label: "Priced well", features: ["price_per_sqft"] },
  { code: "other_yes", label: "Something else", features: [] },
];

const FEATURE_LABELS = {
  parcel_canopy_pct: "Canopy on the lot",
  neighborhood_canopy_pct: "Canopy on the street",
  protected_perimeter_ratio: "Protected perimeter",
  rear_open_distance_ft: "Open space behind",
  fronting_road_class: "Road type",
  arch_style: "Architecture",
  lot_acreage: "Lot size",
  anchor_drive_times: "Drive times",
  flood_zone: "Flood zone",
  price_per_sqft: "Price per sq ft",
  year_built: "Year built",
  abuts_water: "Water adjacency",
};

/* ============================================================
   Parcel plate — the signature element
   ============================================================ */

function ParcelPlate({ listing, w = 420, h = 360 }) {
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

    // buildable — hatched ground with building footprints, reads as a threat
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

/* ---------- Pieces ---------- */

function Figure({ label, value, sub }) {
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

function Bar({ label, value, max, unit, tone }) {
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

function DriveRow({ label, mins, anchor }) {
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

function Card({ children, pad = 24 }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 8, padding: pad }}>
      {children}
    </div>
  );
}

/* ---------- Consider (triage) ---------- */

function Triage({ listing, anchors, onJudge, remaining, done }) {
  const [verdict, setVerdict] = useState(null);
  const [picked, setPicked] = useState([]);
  const [anchorPick, setAnchorPick] = useState([]);

  const tags = verdict === "no" ? NEG_TAGS : POS_TAGS;
  const anchorTagOn = picked.some((c) => tags.find((t) => t.code === c)?.anchorAware);

  function toggle(code) {
    setPicked((p) => (p.includes(code) ? p.filter((c) => c !== code) : [...p, code]));
  }
  function toggleAnchor(id) {
    setAnchorPick((p) => (p.includes(id) ? p.filter((a) => a !== id) : [...p, id]));
  }
  function commit() {
    onJudge(verdict, picked, anchorPick);
    setVerdict(null); setPicked([]); setAnchorPick([]);
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
          {listing.archStyle} · built {listing.yearBuilt} · {listing.beds} bed, {listing.baths} bath · {listing.sqft.toLocaleString()} sq ft
        </p>
      </div>

      <div className="grid gap-5" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))" }}>
        <Card pad={0}>
          <ParcelPlate listing={listing} />
        </Card>
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-center"
            style={{ background: "#EFF2ED", border: `1px solid ${C.line}`, borderRadius: 8, minHeight: 150 }}>
            <span style={{ fontFamily: BODY, fontSize: 12, color: C.mist, textAlign: "center", padding: 16 }}>
              Listing photo<br />wired to listing.photos[0]
            </span>
          </div>
          <div className="grid gap-4" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <Figure label="Asking" value={`$${(listing.price / 1000).toFixed(0)}k`} />
            <Figure label="Lot" value={`${listing.lotAcres} ac`} />
            <Figure label="Street" value={listing.isCulDeSac ? "Cul-de-sac" : listing.roadClass} />
            <Figure label="Flood zone" value={listing.floodZone} />
          </div>
        </div>
      </div>

      <div className="grid gap-6" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))" }}>
        <Card>
          <div style={{ fontFamily: DISPLAY, fontSize: 18, color: C.ink, marginBottom: 14, fontWeight: 400 }}>
            The land
          </div>
          <div className="flex flex-col gap-4">
            <Bar label="Canopy on the lot" value={listing.parcelCanopy} max={100} unit="%" tone={C.canopy} />
            <Bar label="Canopy on the street" value={listing.neighborhoodCanopy} max={100} unit="%" tone={C.canopy} />
            <Bar label="Boundary that's protected" value={Math.round(listing.protectedRatio * 100)} max={100} unit="%" tone={C.tide} />
            <Bar label="Open space behind" value={listing.rearOpenFt} max={400} unit=" ft" tone={C.marsh} />
          </div>
        </Card>
        <Card>
          <div style={{ fontFamily: DISPLAY, fontSize: 18, color: C.ink, marginBottom: 6, fontWeight: 400 }}>
            Getting places
          </div>
          {Object.entries(listing.drives).map(([label, mins]) => (
            <DriveRow key={label} label={label} mins={mins} anchor={anchors.find((a) => a.label === label)} />
          ))}
        </Card>
      </div>

      {!verdict ? (
        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))" }}>
          <button onClick={() => setVerdict("no")} className="py-4"
            style={{ fontFamily: DISPLAY, fontSize: 20, fontWeight: 400, color: C.clay, background: "transparent", border: `1px solid ${C.clay}`, borderRadius: 6, cursor: "pointer" }}>
            Not for us
          </button>
          <button onClick={() => onJudge("maybe", [], [])} className="py-4"
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

/* ---------- Compare ---------- */

function Compare({ pair, anchors, onChoose }) {
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
          <button key={l.id} onClick={() => onChoose(l.id)} className="text-left"
            style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 8, padding: 0, cursor: "pointer", overflow: "hidden" }}>
            <ParcelPlate listing={l} />
            <div style={{ padding: 20 }}>
              <div style={{ fontFamily: DISPLAY, fontSize: 26, fontWeight: 300, color: C.ink, lineHeight: 1.1 }}>
                {l.address}
              </div>
              <div style={{ fontFamily: BODY, fontSize: 13, color: C.inkSoft, marginTop: 6 }}>
                {l.archStyle} · {l.yearBuilt} · ${(l.price / 1000).toFixed(0)}k · {l.lotAcres} ac
              </div>
              <div className="flex flex-col gap-3 mt-4">
                <Bar label="Canopy on the lot" value={l.parcelCanopy} max={100} unit="%" tone={C.canopy} />
                <Bar label="Boundary protected" value={Math.round(l.protectedRatio * 100)} max={100} unit="%" tone={C.tide} />
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

/* ---------- Places ---------- */

function Places({ anchors, setAnchors }) {
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState("People");

  function add() {
    if (!label.trim()) return;
    setAnchors((a) => [...a, { id: Date.now(), label: label.trim(), category, ideal: 15, limit: 30 }]);
    setLabel("");
  }
  function update(id, key, val) {
    setAnchors((a) => a.map((x) => (x.id === id ? { ...x, [key]: Math.max(1, Number(val) || 1) } : x)));
  }
  function remove(id) {
    setAnchors((a) => a.filter((x) => x.id !== id));
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
              {["Beach", "Errands", "People", "Work", "School"].map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <button onClick={add} className="py-3 px-6"
            style={{ fontFamily: DISPLAY, fontSize: 16, background: C.ink, color: C.card, border: "none", borderRadius: 6, cursor: "pointer" }}>
            Add place
          </button>
        </div>
      </Card>

      <div className="flex flex-col gap-3">
        {anchors.map((a) => (
          <Card key={a.id} pad={18}>
            <div className="flex flex-wrap gap-4 items-center justify-between">
              <div style={{ minWidth: 170 }}>
                <div style={{ fontFamily: DISPLAY, fontSize: 20, fontWeight: 400, color: C.ink }}>{a.label}</div>
                <div style={{ fontFamily: BODY, fontSize: 12, color: C.mist }}>{a.category}</div>
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
                      <input type="number" value={a[f.k]} onChange={(e) => update(a.id, f.k, e.target.value)}
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

/* ---------- Patterns ---------- */

function Patterns({ judgments }) {
  const rows = useMemo(() => {
    const acc = {};
    judgments.forEach((j) => {
      const set = j.verdict === "no" ? NEG_TAGS : POS_TAGS;
      (j.tags || []).forEach((code) => {
        const tag = set.find((t) => t.code === code);
        if (!tag) return;
        tag.features.forEach((f) => {
          acc[f] = acc[f] || { credit: 0, blame: 0 };
          if (j.verdict === "no") acc[f].blame += 1; else acc[f].credit += 1;
        });
      });
    });
    return Object.entries(acc).map(([f, v]) => {
      const n = v.credit + v.blame;
      const asym = n ? (v.credit - v.blame) / n : 0;
      let kind = "Cuts both ways";
      if (n < 10) kind = "Still learning";
      else if (asym < -0.5) kind = "Only matters when it's bad";
      else if (asym > 0.5) kind = "Wins you over";
      return { f, ...v, n, kind };
    }).sort((a, b) => b.n - a.n);
  }, [judgments]);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 style={{ fontFamily: DISPLAY, fontSize: 34, fontWeight: 300, color: C.ink, lineHeight: 1.1 }}>
          What you've told it so far
        </h2>
        <p style={{ fontFamily: BODY, fontSize: 15, color: C.inkSoft, marginTop: 8, maxWidth: 560, lineHeight: 1.6 }}>
          Built from this session's tags. The live version reads fitted weights with confidence intervals, and
          shows both of you side by side.
        </p>
      </div>

      {rows.length === 0 ? (
        <Card pad={48}>
          <p style={{ fontFamily: BODY, color: C.inkSoft, textAlign: "center", fontSize: 15 }}>
            Rate a few homes and say why. Your patterns show up here.
          </p>
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          {rows.map((r) => (
            <Card key={r.f} pad={18}>
              <div className="flex justify-between items-baseline mb-3 gap-3 flex-wrap">
                <span style={{ fontFamily: DISPLAY, fontSize: 20, fontWeight: 400, color: C.ink }}>
                  {FEATURE_LABELS[r.f] || r.f}
                </span>
                <span style={{ fontFamily: BODY, fontSize: 12, color: r.kind === "Still learning" ? C.mist : C.tide }}>
                  {r.kind}
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
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Shell ---------- */

export default function App() {
  const [rater, setRater] = useState("zach");
  const [tab, setTab] = useState("triage");
  const [queue, setQueue] = useState(MOCK_LISTINGS.map((l) => l.id));
  const [judgments, setJudgments] = useState([]);
  const [comparisons, setComparisons] = useState([]);
  const [pairIdx, setPairIdx] = useState(0);
  const [anchors, setAnchors] = useState(DEFAULT_ANCHORS);

  const byId = useMemo(() => Object.fromEntries(MOCK_LISTINGS.map((l) => [l.id, l])), []);
  const current = queue.length ? byId[queue[0]] : null;

  const pairs = useMemo(() => {
    const p = [];
    for (let i = 0; i + 1 < MOCK_LISTINGS.length; i += 2) p.push([MOCK_LISTINGS[i], MOCK_LISTINGS[i + 1]]);
    return p;
  }, []);

  function judge(verdict, tags, anchorIds) {
    setJudgments((j) => [...j, { rater, listingId: queue[0], verdict, tags, anchorIds, at: Date.now() }]);
    setQueue((q) => q.slice(1));
  }
  function choose(winnerId) {
    setComparisons((c) => [...c, { rater, pair: pairs[pairIdx].map((l) => l.id), winnerId }]);
    setPairIdx((i) => (i + 1) % pairs.length);
  }

  const mine = judgments.filter((j) => j.rater === rater);
  const TABS = [
    { k: "triage", label: "Consider" },
    { k: "compare", label: "Compare" },
    { k: "places", label: "Places" },
    { k: "patterns", label: "Patterns" },
  ];

  return (
    <div style={{ background: C.paper, minHeight: "100vh" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,500&family=Karla:wght@400;500&family=IBM+Plex+Mono:wght@400&display=swap');
        button:focus-visible, input:focus-visible, select:focus-visible {
          outline: 2px solid ${C.tide}; outline-offset: 2px;
        }
        input, select { outline: none; }
        @media (prefers-reduced-motion: no-preference) {
          button { transition: background 160ms ease, color 160ms ease, border-color 160ms ease; }
        }
      `}</style>

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
            {[{ k: "zach", n: "Zach" }, { k: "partner", n: "Partner" }].map((r) => (
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

        <main className="py-8 pb-20">
          {tab === "triage" && (
            <Triage listing={current} anchors={anchors} onJudge={judge}
              remaining={queue.length} done={mine.length} />
          )}
          {tab === "compare" && <Compare pair={pairs[pairIdx]} anchors={anchors} onChoose={choose} />}
          {tab === "places" && <Places anchors={anchors} setAnchors={setAnchors} />}
          {tab === "patterns" && <Patterns judgments={mine} />}
        </main>

        <footer className="pt-5" style={{ borderTop: `1px solid ${C.line}`, fontFamily: BODY, fontSize: 12, color: C.mist }}>
          {mine.length} considered · {comparisons.filter((c) => c.rater === rater).length} compared · sample data
        </footer>
      </div>
    </div>
  );
}
