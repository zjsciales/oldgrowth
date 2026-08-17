import { BODY, C } from "../theme.js";
import Card from "./Card.jsx";

// Renders only once the on-demand vision pass (useListingVision) has
// resolved for this listing -- no skeleton/spinner beforehand, since
// this is a late-arriving enhancement, not a required field. Callers
// place this last in the page so its arrival never reflows anything a
// rater is actively looking at (UI_SPEC.md's "photo is secondary to the
// plate" precedent extended to this section).
export default function VisionSummary({ listing }) {
  if (!listing?.houseLotSummary) return null;

  const cleared = listing.canopyCondition === "recently_cleared";

  return (
    <Card>
      {cleared && (
        <div
          style={{
            fontFamily: BODY, fontSize: 12, fontWeight: 600, color: C.clay,
            marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.02em",
          }}
        >
          Possible recent clearing detected
        </div>
      )}
      <p style={{ fontFamily: BODY, fontSize: 14, color: C.inkSoft, lineHeight: 1.5 }}>
        {listing.houseLotSummary}
      </p>
      {listing.canopyOverriddenByVision && listing.parcelCanopyRaster != null && (
        <p style={{ fontFamily: BODY, fontSize: 12, color: C.mist, marginTop: 8 }}>
          Raster estimate was {listing.parcelCanopyRaster}% canopy; the photo suggests closer to{" "}
          {listing.parcelCanopy}%.
        </p>
      )}
    </Card>
  );
}
