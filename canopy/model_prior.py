"""Cold-start ridge prior -- the only place stated preferences enter the
system (SCORING_MODEL.md §7). The model in canopy/model.py fits toward
this prior instead of toward zero, and its grip decays as real judgments
accumulate (RIDGE_LAMBDA0/RIDGE_N0 in canopy/model.py). Expect the fitted
coefficients to diverge from these values once there's real data -- that's
the system working, not a bug.

Values are in the same units the model fits in: quantile-normalized
numeric/boolean features are roughly N(0,1), so a coefficient here is
"how many standard deviations of score per standard deviation of feature."
Sign and rough magnitude matter; the exact number doesn't. Any feature not
listed here defaults to 0.0 -- no stated opinion, fully data-driven from
the start."""

FEATURE_SET_VERSION = "v1"  # must match canopy.features.FEATURE_SET_VERSION

COLD_START_PRIOR = {
    # canopy -- the whole reason this project exists. Keyed as
    # effective_canopy_pct (not the raw raster parcel_canopy_pct) since
    # that's what canopy/model.py actually trains on -- see
    # LISTING_FEATURES_NUMERIC_COLUMNS's comment there. Any feature not
    # listed here defaults to 0.0 per this module's docstring, so this key
    # must track whatever model.py currently fits on.
    "effective_canopy_pct": 0.8,
    "neighborhood_canopy_pct": 0.6,
    "canopy_delta": 0.2,
    "canopy_age_proxy": 0.4,
    # lot & surroundings
    "protected_perimeter_ratio": 1.0,
    "abuts_water": 0.3,
    "abuts_marsh_wetland": 0.2,
    "abuts_park_public": 0.2,
    "abuts_conservation_easement": 0.3,
    "abuts_buildable_private": -0.4,
    "rear_open_distance_ft": 0.3,
    "lot_acreage": 0.3,
    "wetland_pct_of_parcel": -0.1,  # cuts both ways per FEATURE_SCHEMA.md; mild negative prior on usable-yard grounds
    # market -- moderate weight, per PROJECT_SUMMARY.md's original stated preferences
    "price_per_sqft": -0.3,
    "list_price": -0.2,
    "hoa_fee_monthly": -0.1,
    # proximity
    "min_drive_beach": -0.15,
    "min_drive_grocery": -0.1,
    "mean_drive_social": -0.1,
}
