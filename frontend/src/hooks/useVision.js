import { useEffect, useRef } from "react";
import { postVision } from "../api.js";

// Fires the on-demand vision call for exactly the listing currently on
// screen, once, after it's already rendered from cached DB data -- never
// ahead of what a rater is actually looking at (cost discipline, same
// intent as the old per-batch vision cap in canopy/api.py). There's no
// loading/error state exposed here on purpose: the summary/badge section
// that consumes the result simply stays absent until (if ever) this
// resolves, rather than showing a spinner for a non-critical enhancement.
export function useListingVision(listing, onResolve) {
  const requested = useRef(new Set());

  useEffect(() => {
    if (!listing || listing.visionComputedAt || requested.current.has(listing.id)) return;
    requested.current.add(listing.id);
    postVision(listing.id)
      .then((data) => onResolve(data.listing))
      .catch(() => {
        // Non-fatal -- the card already rendered without vision fields;
        // allow a later view of this same listing to retry.
        requested.current.delete(listing.id);
      });
  }, [listing?.id, listing?.visionComputedAt]);
}
