# FEATURE_SCHEMA.md — Canopy Preference Layer

Defines the feature vector each listing is reduced to, the tag taxonomy for
Yes/No judgments, and the tables that store both.

Companion doc: `SCORING_MODEL.md` (how these get turned into a ranking).

---

## 1. Design rules

1. **Every listing gets a full feature vector.** No nulls-as-filters. Missing
   values are imputed and flagged, never used to eliminate.
2. **Features must be computable for an unseen listing.** If it can't be
   derived from the pipeline, it isn't a feature.
3. **Tags are NOT features.** Tags only exist on already-judged listings.
   They shape the model's *structure and weights*; they never enter the
   feature vector. Violating this is silent target leakage.
4. **Versioned.** Every feature vector carries `feature_set_version` so
   refits stay reproducible when the schema changes.
5. **Store raw + normalized separately.** Raw for interpretability and
   threshold discovery; normalized for fitting.

---

## 2. Feature catalog

### 2.1 Lot & surroundings — source: county ArcGIS + parcel geometry

| Feature | Type | Notes |
|---|---|---|
| `lot_acreage` | float | |
| `lot_depth_ft` | float | Derived from geometry; depth matters more than area for privacy |
| `lot_width_ft` | float | Frontage |
| `protected_perimeter_ratio` | float 0–1 | **Key feature.** Share of parcel perimeter abutting water, marsh, park, or conservation land. Replaces the boolean adjacency flags as the primary signal |
| `abuts_water` | bool | Kept as separate flags for interpretability |
| `abuts_marsh_wetland` | bool | |
| `abuts_park_public` | bool | |
| `abuts_conservation_easement` | bool | |
| `abuts_buildable_private` | bool | The negative case — a neighbor can build |
| `rear_open_distance_ft` | float | Distance from rear lot line to nearest structure/buildable envelope |
| `wetland_pct_of_parcel` | float 0–1 | Own-parcel wetland — cuts both ways (privacy vs. usable yard) |
| `flood_zone` | categorical | X / AE / VE / etc. |

### 2.2 Canopy — source: NLCD or higher-res raster

| Feature | Type | Notes |
|---|---|---|
| `parcel_canopy_pct` | float 0–100 | Canopy on the lot itself |
| `neighborhood_canopy_pct` | float 0–100 | Canopy within a ~150m buffer |
| `canopy_delta` | float | `neighborhood − parcel`. Captures "wooded street, open yard" vs. the reverse |
| `median_year_built_buffer` | int | Old-growth proxy — neighborhood age within buffer |
| `canopy_age_proxy` | float | Composite of `neighborhood_canopy_pct` × `median_year_built_buffer`. Explicitly a heuristic; validate against ratings before trusting |

> Splitting parcel vs. neighborhood canopy is the single most likely fix for
> the 2-of-1025 problem. "Old growth neighborhood" is probably mostly the
> neighborhood term, and the original single metric conflated them.

### 2.3 Road & position — source: OpenStreetMap

| Feature | Type | Notes |
|---|---|---|
| `fronting_road_class` | categorical | residential / tertiary / secondary / primary |
| `dist_to_arterial_m` | float | Distance to nearest secondary-or-larger road |
| `is_cul_de_sac` | bool | |
| `is_dead_end` | bool | |
| `through_traffic_proxy` | float | Intersection density within buffer |
| `front_setback_ft` | float | Structure centroid to front lot line |

Answers "main street or back street" without either of you self-reporting it.

### 2.4 Proximity — drive-time to named anchors

Stored as rows in `anchors` / `listing_anchor_times`, **not** as columns, so
you can add anchors without a migration.

Anchors are specific named points you both enter — "Wrightsville Beach
public access," "the Robertsons," "Harris Teeter on Oleander" — not vague
categories. Each anchor has a `category` so the model can learn a weight per
category as well as per point.

| Field | Notes |
|---|---|
| `drive_minutes` | Primary measure |
| `straight_line_km` | Cheap fallback |
| `anchor_category` | beach / grocery / social / work / school |

Derived rollups available to the model: `min_drive_beach`,
`min_drive_grocery`, `mean_drive_social`.

### 2.5 Structure & architecture — source: listing data (Zillow alert email) + Claude vision pass

| Feature | Type | Notes |
|---|---|---|
| `year_built` | int | |
| `sqft`, `beds`, `baths`, `stories` | numeric | |
| `arch_style` | categorical | Vision-tagged: craftsman / ranch / coastal contemporary / colonial revival / cottage / new traditional / other |
| `arch_style_confidence` | float 0–1 | Down-weight low-confidence tags during fitting |
| `exterior_material` | categorical | Vision-tagged |
| `has_front_porch` | bool | Vision-tagged |
| `garage_type` | categorical | none / attached / detached / carport |
| `visible_renovation_recency` | categorical | Vision-tagged: original / dated reno / recent reno |

The vision pass is where architecture becomes learnable instead of vibes.

### 2.6 Listing & market — source: listing data (Zillow alert email)

| Feature | Type |
|---|---|
| `list_price` | float |
| `price_per_sqft` | float |
| `days_on_market` | int |
| `price_cut_count` | int |
| `hoa_fee_monthly` | float |

---

## 3. Tag taxonomy

Each tag maps to one or more features. That mapping is the bridge that makes
tags actionable rather than decorative — it's how a tag adjusts a weight.

### 3.1 Negative tags (why no)

| Code | Label | Maps to |
|---|---|---|
| `road_too_busy` | Too close to a busy road | `fronting_road_class`, `dist_to_arterial_m`, `through_traffic_proxy` |
| `lot_too_open` | Lot too open / not enough trees | `parcel_canopy_pct` |
| `street_too_bare` | Street lacks canopy | `neighborhood_canopy_pct` |
| `neighbors_too_close` | Neighbors on top of us | `lot_width_ft`, `rear_open_distance_ft` |
| `backs_to_buildable` | Someone can build behind it | `abuts_buildable_private`, `protected_perimeter_ratio` |
| `wrong_architecture` | Wrong style | `arch_style`, `exterior_material` |
| `too_far_beach` | Too far from beach | `min_drive_beach` |
| `too_far_social` | Too far from people we know | `mean_drive_social` |
| `too_far_errands` | Too far from stores | `min_drive_grocery` |
| `flood_risk` | Flood exposure | `flood_zone`, `wetland_pct_of_parcel` |
| `lot_too_small` | Lot too small | `lot_acreage`, `lot_depth_ft` |
| `overpriced` | Not worth the price | `price_per_sqft` |
| `house_too_small` | House too small | `sqft`, `beds` |
| `too_renovated` | Character stripped out | `visible_renovation_recency`, `year_built` |
| `hoa_objection` | HOA | `hoa_fee_monthly` |
| `other_no` | Something else (free text) | — feeds feature discovery |

### 3.2 Positive tags (why yes)

| Code | Label | Maps to |
|---|---|---|
| `great_rear_privacy` | Protected behind it | `protected_perimeter_ratio`, `rear_open_distance_ft` |
| `mature_canopy` | Beautiful trees on the lot | `parcel_canopy_pct` |
| `wooded_street` | Whole street is wooded | `neighborhood_canopy_pct`, `median_year_built_buffer` |
| `quiet_street` | Quiet / low traffic | `fronting_road_class`, `is_cul_de_sac` |
| `water_adjacency` | Water or marsh access/view | `abuts_water`, `abuts_marsh_wetland` |
| `love_architecture` | Love the style | `arch_style`, `exterior_material` |
| `period_character` | Real character / period details | `year_built`, `visible_renovation_recency` |
| `big_lot` | Great lot size | `lot_acreage` |
| `outdoor_living` | Porch / outdoor space | `has_front_porch` |
| `great_location` | Well placed for our life | anchor drive times |
| `good_value` | Priced well | `price_per_sqft` |
| `other_yes` | Something else (free text) | — feeds feature discovery |

### 3.3 What the tags are used for

1. **Threshold discovery.** The distribution of `parcel_canopy_pct` among
   listings tagged `lot_too_open` gives the empirical dealbreaker threshold.
   The distribution among `mature_canopy` gives the delight threshold. This
   is the direct answer to "what canopy number are we comfortable with."
2. **Hygiene vs. delighter classification.** Per feature, compare how often
   it's credited in Yes-tags vs. blamed in No-tags. Strong asymmetry triggers
   a hinge basis expansion (see `SCORING_MODEL.md` §4).
3. **Coefficient priors.** Tag frequency nudges the ridge prior toward
   features you demonstrably care about, which helps a lot at low n.
4. **Feature discovery.** Recurring `other_yes` / `other_no` free text is a
   feature you haven't built yet. Review monthly.
5. **Disagreement diagnosis.** Both rate a listing Yes but with different
   tags = agreement for different reasons, which is fragile. Worth surfacing.

---

## 4. SQL DDL

```sql
-- ---------- Feature storage ----------

CREATE TABLE listing_features (
  listing_id            TEXT NOT NULL REFERENCES listings(id),
  feature_set_version   TEXT NOT NULL,
  computed_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- lot & surroundings
  lot_acreage               REAL,
  lot_depth_ft              REAL,
  lot_width_ft              REAL,
  protected_perimeter_ratio REAL,
  abuts_water               BOOLEAN,
  abuts_marsh_wetland       BOOLEAN,
  abuts_park_public         BOOLEAN,
  abuts_conservation_easement BOOLEAN,
  abuts_buildable_private   BOOLEAN,
  rear_open_distance_ft     REAL,
  wetland_pct_of_parcel     REAL,
  flood_zone                TEXT,

  -- canopy
  parcel_canopy_pct         REAL,
  neighborhood_canopy_pct   REAL,
  canopy_delta              REAL,
  median_year_built_buffer  INT,

  -- road & position
  fronting_road_class       TEXT,
  dist_to_arterial_m        REAL,
  is_cul_de_sac             BOOLEAN,
  is_dead_end               BOOLEAN,
  through_traffic_proxy     REAL,
  front_setback_ft          REAL,

  -- structure & architecture
  year_built                INT,
  sqft                      INT,
  beds                      REAL,
  baths                     REAL,
  stories                   REAL,
  arch_style                TEXT,
  arch_style_confidence     REAL,
  exterior_material         TEXT,
  has_front_porch           BOOLEAN,
  garage_type               TEXT,
  visible_renovation_recency TEXT,

  -- market
  list_price                REAL,
  price_per_sqft            REAL,
  days_on_market            INT,
  price_cut_count           INT,
  hoa_fee_monthly           REAL,

  -- imputation tracking
  imputed_fields            TEXT[] DEFAULT '{}',

  -- experimental features before promotion to columns
  extra                     JSONB DEFAULT '{}',

  PRIMARY KEY (listing_id, feature_set_version)
);

-- ---------- Anchors (proximity) ----------

CREATE TABLE anchors (
  id          SERIAL PRIMARY KEY,
  label       TEXT NOT NULL,
  category    TEXT NOT NULL,   -- beach | grocery | social | work | school
  lat         DOUBLE PRECISION NOT NULL,
  lon         DOUBLE PRECISION NOT NULL,
  created_by  TEXT NOT NULL,   -- rater id; either partner can add anchors
  active      BOOLEAN DEFAULT TRUE
);

CREATE TABLE listing_anchor_times (
  listing_id       TEXT NOT NULL REFERENCES listings(id),
  anchor_id        INT  NOT NULL REFERENCES anchors(id),
  drive_minutes    REAL,
  straight_line_km REAL,
  computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (listing_id, anchor_id)
);

-- ---------- Raters & judgments ----------

CREATE TABLE raters (
  id           TEXT PRIMARY KEY,   -- 'zach' | 'wife'
  display_name TEXT NOT NULL
);

CREATE TABLE judgments (
  id                  BIGSERIAL PRIMARY KEY,
  rater_id            TEXT NOT NULL REFERENCES raters(id),
  listing_id          TEXT NOT NULL REFERENCES listings(id),
  mode                TEXT NOT NULL,   -- 'swipe' | 'detail'
  verdict             TEXT NOT NULL,   -- 'yes' | 'no' | 'maybe'
  session_id          TEXT NOT NULL,   -- groups a rating batch
  feature_set_version TEXT NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (rater_id, listing_id, created_at)
);

CREATE TABLE tags (
  code             TEXT PRIMARY KEY,
  label            TEXT NOT NULL,
  polarity         TEXT NOT NULL,   -- 'positive' | 'negative'
  mapped_features  TEXT[] NOT NULL,
  active           BOOLEAN DEFAULT TRUE
);

CREATE TABLE judgment_tags (
  judgment_id  BIGINT NOT NULL REFERENCES judgments(id) ON DELETE CASCADE,
  tag_code     TEXT   NOT NULL REFERENCES tags(code),
  free_text    TEXT,            -- only for other_yes / other_no
  PRIMARY KEY (judgment_id, tag_code)
);

CREATE TABLE pairwise_comparisons (
  id                  BIGSERIAL PRIMARY KEY,
  rater_id            TEXT NOT NULL REFERENCES raters(id),
  listing_a           TEXT NOT NULL REFERENCES listings(id),
  listing_b           TEXT NOT NULL REFERENCES listings(id),
  winner              TEXT NOT NULL,   -- 'a' | 'b' | 'tie'
  selection_strategy  TEXT,            -- 'active' | 'random' | 'top_ranked'
  feature_set_version TEXT NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Model & scores ----------

CREATE TABLE model_runs (
  id                  BIGSERIAL PRIMARY KEY,
  rater_id            TEXT NOT NULL REFERENCES raters(id),
  feature_set_version TEXT NOT NULL,
  trained_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  n_pairs             INT  NOT NULL,
  coefficients        JSONB NOT NULL,  -- {feature: weight}
  coef_ci             JSONB,           -- {feature: [lo, hi]} bootstrap
  scaler_params       JSONB NOT NULL,  -- quantile/z params for reproducibility
  basis_config        JSONB,           -- hinge terms active this run
  holdout_accuracy    REAL,
  baseline_accuracy   REAL             -- price-only model, sanity check
);

CREATE TABLE scores (
  listing_id    TEXT   NOT NULL REFERENCES listings(id),
  model_run_id  BIGINT NOT NULL REFERENCES model_runs(id),
  raw_score     REAL   NOT NULL,
  display_score REAL   NOT NULL,       -- 0-100, percentile-normalized
  pred_variance REAL,                  -- bootstrap variance, for active sampling
  PRIMARY KEY (listing_id, model_run_id)
);
```

---

## 5. Cold start

Before there are ratings, seed `model_runs` with a hand-set coefficient
vector from your current stated preferences. It's the ridge prior in
`SCORING_MODEL.md` §3, and it decays as real judgments accumulate. The
stated preferences aren't wrong — they're just a prior, and the whole point
is that data overrides them.

---

## Implementation notes (2026-08-12)

Deviations from this doc found necessary during the build. This section
is a changelog, not a spec revision — the sections above stay as
originally designed except where noted here.

- **Table naming**: the new `scores` table (§4 DDL) collides with the
  pre-existing deterministic-canopy `Score`/`scores` table from the v1
  filter design, which is still in active use (`canopy/scoring.py`). The
  new table is named `preference_scores` instead.
- **Rater ids**: `zach` / `andrea` (real names), not the illustrative
  `zach` / `wife` in §4's DDL comment.
- **`median_year_built_buffer`** (§2.2): no NHC GIS layer exposes
  year-built — checked live against `Layers/Parcels`,
  `Thematic/NHC_PropertiesAndBuildings`'s `Parcel_Polygon`,
  `Layers/PropertyOwners`, and `Layers/IASTAX`. Computed instead from our
  own already-ingested `Listing.year_built` rows within a radius —
  coverage is necessarily partial (only areas we've ingested listings
  in), which is fine under this doc's own imputation rule (§1.1).
- **`rear_open_distance_ft`** (§2.1): better than expected — a real
  county building-footprint layer (`Layers/BuildingFootprints`) was found
  live during development and is used directly (joined to a parcel via
  its own `Parcel_ID` field, confirmed to match `Parcels.PID` format),
  not a proxy.
- **Anchor rollups** (§2.4): implemented as exactly five features —
  `min_drive_beach`, `min_drive_grocery`, `min_drive_work`,
  `min_drive_school` (MIN — "the closest one is what matters"), and
  `mean_drive_social` (MEAN — proximity to a network of people, not just
  the nearest one) — rather than the illustrative subset this doc names.
- **Anchor drive times**: `listing_anchor_times.drive_minutes` is
  currently a haversine-distance proxy (`is_proxy=True`), not real
  routing — real routing is deferred; see `ARCHITECTURE.md`'s Known
  Limitations.
- **§2.3 (road & position features) is entirely deferred** — columns
  exist on `listing_features` (reserved), but no OpenStreetMap
  integration has been built yet.
- **Structure/architecture features (§2.5)** are populated lazily, once
  per listing on first view (`canopy/vision.py`), not in the weekly bulk
  feature-computation pass — running Claude vision on the full weekly
  listing volume would blow past this project's cost discipline.
