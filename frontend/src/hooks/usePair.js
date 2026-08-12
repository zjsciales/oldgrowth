import { useCallback, useEffect, useState } from "react";
import { getPair, postComparison } from "../api.js";

export function usePair(rater) {
  const [pair, setPair] = useState(null);
  const [strategy, setStrategy] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    return getPair(rater)
      .then((data) => {
        setPair([data.listing_a, data.listing_b]);
        setStrategy(data.selection_strategy);
      })
      .catch((err) => {
        setPair(null);
        setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [rater]);

  useEffect(() => { refresh(); }, [refresh]);

  async function choose(winnerId) {
    if (!pair) return;
    const winner = pair[0].id === winnerId ? "a" : "b";
    await postComparison({
      rater_id: rater,
      listing_a: pair[0].id,
      listing_b: pair[1].id,
      winner,
      selection_strategy: strategy,
    });
    refresh();
  }

  return { pair, strategy, loading, error, choose };
}
