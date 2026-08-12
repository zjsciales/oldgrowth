import { useCallback, useEffect, useState } from "react";
import { createAnchor, deleteAnchor, listAnchors, updateAnchor } from "../api.js";

export function useAnchors() {
  const [anchors, setAnchors] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    return listAnchors()
      .then((data) => setAnchors(data.anchors))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function add(payload) {
    const anchor = await createAnchor(payload);
    setAnchors((prev) => [...prev, anchor]);
    return anchor;
  }

  async function update(id, payload) {
    const anchor = await updateAnchor(id, payload);
    setAnchors((prev) => prev.map((a) => (a.id === id ? anchor : a)));
    return anchor;
  }

  async function remove(id) {
    await deleteAnchor(id);
    setAnchors((prev) => prev.filter((a) => a.id !== id));
  }

  return { anchors, loading, add, update, remove, refresh };
}
