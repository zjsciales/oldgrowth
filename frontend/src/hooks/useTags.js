import { useEffect, useState } from "react";
import { getTags } from "../api.js";

export function useTags() {
  const [tags, setTags] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getTags()
      .then((data) => { if (!cancelled) setTags(data.tags); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return {
    tags,
    negTags: tags.filter((t) => t.polarity === "negative"),
    posTags: tags.filter((t) => t.polarity === "positive"),
    loading,
  };
}
