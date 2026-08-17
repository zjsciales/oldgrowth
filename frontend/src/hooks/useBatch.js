import { useCallback, useEffect, useState } from "react";
import { getBatch, postJudgment } from "../api.js";

// Rater switch must trigger a real refetch, not a client-side re-filter --
// otherwise a batch fetched under the old rater could leak into a
// judgment payload for the new one (UI_SPEC.md §6: rater switch is global
// and always visible; no shared judgments, ever).
export function useBatch(rater) {
  const [queue, setQueue] = useState([]);
  const [done, setDone] = useState(0);
  const [loading, setLoading] = useState(true);
  const [batchId, setBatchId] = useState(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setDone(0);
    return getBatch(rater)
      .then((data) => {
        setQueue(data.listings);
        setBatchId(data.batch_id);
      })
      .finally(() => setLoading(false));
  }, [rater]);

  useEffect(() => { refresh(); }, [refresh]);

  async function judge(verdict, tags, anchorIds) {
    const listing = queue[0];
    if (!listing) return;
    const payload = {
      rater_id: rater,
      listing_id: listing.id,
      mode: "swipe",
      verdict,
      session_id: batchId,
      tags,
    };
    // omitted entirely (not sent as []) when no anchor-aware tag was
    // picked -- never gate saving on anchor attribution (UI_SPEC.md §6)
    if (anchorIds && anchorIds.length) payload.anchor_ids = anchorIds;
    await postJudgment(payload);
    setQueue((q) => q.slice(1));
    setDone((d) => d + 1);
  }

  // Merges an updated listing (e.g. vision-pass results arriving after
  // the initial batch load, see useListingVision) into the queue in
  // place, without a refetch.
  function patchListing(id, patch) {
    setQueue((q) => q.map((l) => (l.id === id ? { ...l, ...patch } : l)));
  }

  return { current: queue[0] || null, remaining: queue.length, done, loading, judge, refresh, patchListing };
}
