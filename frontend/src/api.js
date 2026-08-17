// Thin fetch wrappers over canopy/api.py. Relative paths work both under
// Vite's dev proxy (vite.config.js) and under Flask's static serving in
// production -- no base-URL config needed.

async function request(path, options = {}) {
  const resp = await fetch(path, {
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });
  if (!resp.ok) {
    let message = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body.error) message = body.error;
    } catch {
      // response wasn't JSON -- keep the status line
    }
    throw new Error(message);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

export function getBatch(rater, n = 40) {
  return request(`/api/batch?rater=${encodeURIComponent(rater)}&n=${n}`);
}

export function getPair(rater) {
  return request(`/api/pair?rater=${encodeURIComponent(rater)}`);
}

export function postJudgment(payload) {
  return request("/api/judgment", { method: "POST", body: JSON.stringify(payload) });
}

export function postComparison(payload) {
  return request("/api/comparison", { method: "POST", body: JSON.stringify(payload) });
}

export function postVision(listingId) {
  return request(`/api/listings/${encodeURIComponent(listingId)}/vision`, { method: "POST" });
}

export function getWeights(rater) {
  return request(`/api/weights?rater=${encodeURIComponent(rater)}`);
}

export function getTags() {
  return request("/api/tags");
}

export function listAnchors() {
  return request("/api/anchors");
}

export function createAnchor(payload) {
  return request("/api/anchors", { method: "POST", body: JSON.stringify(payload) });
}

export function updateAnchor(id, payload) {
  return request(`/api/anchors/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteAnchor(id) {
  return request(`/api/anchors/${id}`, { method: "DELETE" });
}
