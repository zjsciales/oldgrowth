// Transcribed from docs/RatingUI.jsx -- keep in sync if the prototype's
// palette changes. See docs/UI_SPEC.md §1 for the design rationale
// (high-key coastal morning, not a dark GIS instrument).

export const C = {
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

export const DISPLAY = "'Fraunces', Georgia, serif";
export const BODY = "'Karla', system-ui, sans-serif";
export const NUM = "'IBM Plex Mono', ui-monospace, monospace";

// Matches ListingCard.edges values from the API (canopy/api.py) exactly:
// water / marsh / park / conservation / buildable / road.
export const EDGE_META = {
  water: { label: "Open water", color: C.tide },
  marsh: { label: "Marsh", color: C.marsh },
  park: { label: "Park", color: C.canopyDeep },
  conservation: { label: "Conservation land", color: C.canopyDeep },
  buildable: { label: "Buildable lot", color: C.slate },
  road: { label: "Road", color: C.slate },
};
