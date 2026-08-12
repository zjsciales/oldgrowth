# UI_SPEC.md — Canopy Rating UI (v2)

Handoff notes for `RatingUI.jsx`. Read with `FEATURE_SCHEMA.md` and
`SCORING_MODEL.md`. Where this doc and the earlier ones disagree, this one
wins — it reflects the v2 revisions.

---

## 1. Aesthetic direction

The first pass was a dark GIS instrument. Wrong brief. Choosing this house is
supposed to feel like the good part of your life, not like operating
equipment.

v2 is high-key coastal morning: a green-cool near-white ground (`#F6F8F4`),
pine ink rather than black, and light-weight Fraunces set large with real air
around it. Sentence case everywhere — no tracked-out uppercase labels.
Generous whitespace is doing the emotional work, so resist tightening it.

| Role | Value |
|---|---|
| Ground | `#F6F8F4` |
| Card | `#FDFCF8` |
| Ink | `#1B3A31` pine |
| Canopy | `#6FA368` / deep `#3E6B45` |
| Tide | `#5B9AA8` |
| Marsh | `#C3A45C` |
| Clay (negative only) | `#B5705A` |
| Display | Fraunces, weights 300–400, set large |
| Body | Karla |
| Numerals | IBM Plex Mono, data only |

Clay appears only on rejection. Nothing else in the palette carries alarm,
which is deliberate — the interface should never feel like it's grading you.

---

## 2. The parcel plate

### 2.1 Canopy is coverage, not dots

v1 drew a fixed *count* of stipple dots, so 74% canopy rendered as scattered
specks that read like tree trunks. Fixed. Crowns are now sized as a fraction
of lot width (~8.5%) and the count derives from the coverage equation:

```
c = 1 - exp(-n·a/A)   →   n = -ln(1-c) · A/a
```

where `a` is crown area and `A` is lot area. This self-corrects for random
overlap, so a plate labelled 74% actually covers about 74% of the lot. Crowns
render in two layers — a blurred base at 0.62 opacity and a smaller darker
core at 0.5 — so they merge into a canopy mass rather than reading as
individual objects. Clipped to the lot rect.

Neighborhood canopy scatters at lower density across the full plate behind
the edge bands, so a wooded street is visible as ambient green even when the
lot itself is open. `canopy_delta` becomes something you can see.

### 2.2 Edges are textured bands, not colored lines

Each of the four boundaries renders as a 46px band with its own treatment:

| Abutting | Treatment |
|---|---|
| Open water | Pale tidal wash, hand-drawn wave lines |
| Marsh | Sand-gold wash with grass tufts |
| Park / conservation | Deep green with dense crown texture |
| Buildable lot | Grey diagonal hatch with outlined building footprints |
| Road | Flat grey with dashed centerline |

The buildable treatment is the important one. In v1 an unprotected edge was a
thin dashed line — an absence, easy to overlook. Drawing implied houses on it
makes the risk *visible*: you see what could be built there. That single
change is probably worth more than the rest of the plate combined, since
"someone can build behind it" is a top rejection reason.

### 2.3 Determinism

All randomness is seeded from the listing ID. A given lot renders identically
in Consider and in Compare. This is not cosmetic — inconsistent rendering
between views would be an uncontrolled variable inside the pairwise training
data. Preserve it if the plate gets refactored, and keep `ParcelPlate` pure.

SVG `<defs>` IDs are namespaced per listing (`p{id}-hatch`, `p{id}-lot`,
`p{id}-soft`). Two plates render side by side in Compare, and un-namespaced
IDs would collide and cross-apply.

---

## 3. Anchors and how they reach the model

The Places tab is a shared list — one set for both raters. Either partner can
add a place; both see the same list. Each anchor carries two tolerances:

- **`ideal`** — a drive that still feels easy
- **`limit`** — past this, it stops being worth it

### 3.1 What the tolerances actually do

They are **priors, not rules**. Specifically, they seed the hinge thresholds
from `SCORING_MODEL.md` §4.2 for anchor-distance features before there's
enough tagged data to learn them:

```
τ_hi (delight boundary)    ← anchor.ideal
τ_lo (dealbreaker boundary) ← anchor.limit
```

Once ~10 judgments carry `well_placed` or `too_far`, the learned thresholds
computed from tag distributions take over, and the entered numbers are
retained only as a display reference. This resolves the cold-start problem for
proximity — the app is useful on day one — without letting a guessed number
harden into the filter that failed you the first time.

The tolerance also drives the per-listing display state (*within ideal* /
*workable* / *past your limit*), so the numbers stay legible while you rate.

### 3.2 Anchor attribution on tags

`well_placed` and `too_far` are marked `anchorAware`. Selecting either reveals
a second, optional row: **which places were you thinking of?**

This solves a real attribution problem. "Well placed for us" on its own can't
tell the model whether the beach drive, the grocery drive, or proximity to
friends did the work — the model would have to infer it from correlation
across many judgments, which is slow and unreliable when anchors are
correlated (and in a small city, they will be). One extra tap resolves it
directly.

Weighting structure:

- **Per-anchor weight** — learned for each specific place. Some friends matter
  more than others, and the model shouldn't pretend otherwise.
- **Per-category rollup** (`beach`, `errands`, `people`, `work`, `school`) —
  pooled weight, used as a prior for newly added anchors so a new place isn't
  cold.
- **Attribution boost** — when a judgment names specific anchors, only those
  anchors' features receive credit or blame. Unattributed `well_placed` tags
  distribute across all anchors, weighted by category prior.

### 3.3 Anchors are not filters

Worth stating plainly, given the history: exceeding `limit` costs a listing
rank. It never removes it. A home 40 minutes from the beach with 0.7 protected
perimeter and old-growth canopy should still surface, and you should get to be
the one who says no.

---

## 4. Tag changes in v2

| v1 | v2 | Why |
|---|---|---|
| `great_rear_privacy` "Protected behind it" | `abuts_protected` "Abuts protected land" **and** `feels_private` "Feels private" | The original conflated two different things — legal protection of adjacent land, and felt privacy. They map to different features (`protected_perimeter_ratio` vs `rear_open_distance_ft`) and can diverge sharply: a lot can abut conservation land and still feel exposed if the house sits close to the line. One tag couldn't tell the model which |
| `neighbors_too_close` | `not_private` "Doesn't feel private" | Mirror of `feels_private`, so positive and negative sides map to the same feature |
| `too_far_beach` / `too_far_social` / `too_far_errands` | `too_far` + anchor attribution | Fixed per-category tags don't survive a user-defined anchor list. Attribution is more precise anyway |
| `great_location` | `well_placed` + anchor attribution | Same |

---

## 5. API contract

```
GET  /api/batch?rater={id}&n=40      → { listings: [ListingCard], batch_id }
GET  /api/pair?rater={id}            → { listing_a, listing_b, selection_strategy }
POST /api/judgment                   → see below
POST /api/comparison                 → { rater_id, listing_a, listing_b, winner, ... }
GET  /api/weights?rater={id}         → coefficients, CIs, thresholds, classification
GET  /api/tags                       → taxonomy, so vocabulary changes need no redeploy
GET  /api/anchors                    → shared list
POST /api/anchors                    → { label, category, ideal, limit } — geocode server-side
PATCH /api/anchors/{id}              → { ideal?, limit? }
DELETE /api/anchors/{id}
```

Judgment payload gains anchor attribution:

```json
{
  "rater_id": "zach",
  "listing_id": "L-1042",
  "verdict": "yes",
  "tags": ["abuts_protected", "well_placed"],
  "anchor_ids": [1, 3],
  "free_text": null,
  "session_id": "...",
  "feature_set_version": "v1"
}
```

ListingCard adds `edges` (four compass boundaries resolved server-side to a
dominant abutting type — don't ship raw geometry to the client),
`rear_open_ft`, and `drives` keyed by anchor label.

### Schema additions

```sql
ALTER TABLE anchors ADD COLUMN ideal_minutes INT DEFAULT 15;
ALTER TABLE anchors ADD COLUMN limit_minutes INT DEFAULT 30;
-- anchors.created_by stays, but the list is shared; it's provenance, not scope

CREATE TABLE judgment_anchors (
  judgment_id BIGINT NOT NULL REFERENCES judgments(id) ON DELETE CASCADE,
  anchor_id   INT    NOT NULL REFERENCES anchors(id),
  PRIMARY KEY (judgment_id, anchor_id)
);
```

---

## 6. Interaction decisions to preserve

- **Tags come after the verdict.** Snap judgment first, rationalize second.
  Showing the tag list first turns a reaction into an argument.
- **Maybe skips tagging.** Low-information label; adding friction would push
  people to Yes/No for the wrong reason.
- **Anchor attribution is optional and progressive.** It only appears when an
  anchor-aware tag is selected. Never gate saving on it.
- **Rater switch is global and always visible.** No shared judgments, ever.
- **Photo is secondary to the plate.** Satellite and street imagery show
  canopy but not parcel lines or what's buildable next door — precisely the
  information that was missing.

---

## 7. Still to build

- **The disagreement view** — "you two see these differently," from
  `SCORING_MODEL.md` §5. Needs two fitted models, so it couldn't be
  prototyped. It is arguably the most valuable screen in the app; don't let it
  slide to last just because it's listed last. **Shipped in the digest
  email** (a dedicated section) as of the rating-pivot build; a dedicated
  in-app screen for it is still not built.
- Free-text capture on `other_yes` / `other_no`.
- Address autocomplete + server-side geocoding on the Places tab. **Raw
  geocoding shipped** (the Places tab's single text field is geocoded
  server-side via Mapbox) — only the autocomplete-as-you-type UX is still
  deferred.
- Offline queueing for judgments — rating happens on a couch, not at a desk.
- Keyboard shortcuts in Consider (`j` / `k` / `space`).
- Undo on the last judgment. A wrong label is worse than a missing one.

---

## Implementation notes (2026-08-12)

The live implementation is `frontend/src/` (Vite + React), componentized
from `RatingUI.jsx` per this doc's design. `RatingUI.jsx` in this
directory stays as the original historical prototype/reference — not
maintained, not wired to anything.

- **Anchor drive times are a haversine proxy** in the current build
  (`ListingAnchorTime.is_proxy=True`), not real routing — ships the
  Places tab and proximity ranking signal from day one per §3.1's intent,
  but "workable"/"past your limit" `DriveRow` states are only as accurate
  as straight-line distance until real routing lands.
- **`ListingCard.edges`** (§5): resolving a dominant type per compass
  side turned out to need new server-side geometry work not originally
  scoped in `FEATURE_SCHEMA.md` — see that doc's Implementation notes.
  Cached in `ListingFeatures.extra["edges"]` at feature-computation time,
  not computed live per request.
- **`/api/weights`** was extended beyond this doc's original fields to
  include `tagStats` (per-feature credit/blame/kind) — needed by the
  Patterns tab preview and not something `SCORING_MODEL.md`'s
  `ModelRun`/`coefficients` alone could provide.
