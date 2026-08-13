import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Listing(Base):
    """One RentCast sale listing, upserted on each ingest run."""

    __tablename__ = "listings"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # RentCast listing id
    formatted_address: Mapped[str] = mapped_column(String)
    city: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    zip_code: Mapped[str] = mapped_column(String, index=True)
    county: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)

    property_type: Mapped[str | None] = mapped_column(String, nullable=True)
    lot_size_sqft: Mapped[float | None] = mapped_column(Float, nullable=True)
    square_footage: Mapped[float | None] = mapped_column(Float, nullable=True)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String)  # Active / Inactive
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    listed_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    removed_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_date: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    mls_name: Mapped[str | None] = mapped_column(String, nullable=True)
    mls_number: Mapped[str | None] = mapped_column(String, nullable=True)

    raw: Mapped[dict] = mapped_column(JSON)  # full RentCast payload, for reference

    first_seen: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    last_ingested: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    parcel: Mapped["Parcel | None"] = relationship(back_populates="listing", uselist=False)
    score: Mapped["Score | None"] = relationship(back_populates="listing", uselist=False)


class Parcel(Base):
    """Stage 2 GIS enrichment results for a listing's parcel."""

    __tablename__ = "parcels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), unique=True)

    parcel_id: Mapped[str | None] = mapped_column(String, nullable=True)
    geometry_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    adjacent_water: Mapped[bool] = mapped_column(default=False)
    adjacent_park_or_conservation: Mapped[bool] = mapped_column(default=False)
    adjacent_county_or_city_owned: Mapped[bool] = mapped_column(default=False)

    flood_zone: Mapped[str | None] = mapped_column(String, nullable=True)
    wetland_overlay: Mapped[bool] = mapped_column(default=False)

    raw_gis: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    enriched_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    listing: Mapped["Listing"] = relationship(back_populates="parcel")


class Score(Base):
    """Stage 3 deterministic canopy scoring for a listing. The old
    pass/fail filter fields (passed_filter, filter_reasons,
    subagent_flag_ok) were retired with the hard filter itself -- binary
    pass/fail doesn't fit "rank, never eliminate." subagent_rationale is
    now written by the lazy vision call (canopy/vision.py) on first view,
    not gated to a filtered shortlist."""

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), unique=True)

    canopy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    old_growth_proxy_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    subagent_rationale: Mapped[str | None] = mapped_column(String, nullable=True)

    scored_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    listing: Mapped["Listing"] = relationship(back_populates="score")


class DigestLog(Base):
    """Record of what was emailed and when. An audit log, not a suppression
    filter -- a ranked listing can legitimately resurface if its rank or
    uncertainty changes week to week."""

    __tablename__ = "digest_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    sent_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# Preference layer -- see docs/FEATURE_SCHEMA.md and docs/SCORING_MODEL.md.
# Every listing gets a feature vector and is ranked, never hard-filtered.
# ---------------------------------------------------------------------------


class ListingFeatures(Base):
    """Full feature vector for one listing, versioned so refits stay
    reproducible when the schema changes. Raw values only -- normalization
    happens at model-fit time (canopy/model.py), never stored here."""

    __tablename__ = "listing_features"

    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), primary_key=True)
    feature_set_version: Mapped[str] = mapped_column(String, primary_key=True)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    # lot & surroundings
    lot_acreage: Mapped[float | None] = mapped_column(Float, nullable=True)
    lot_depth_ft: Mapped[float | None] = mapped_column(Float, nullable=True)
    lot_width_ft: Mapped[float | None] = mapped_column(Float, nullable=True)
    protected_perimeter_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    abuts_water: Mapped[bool | None] = mapped_column(nullable=True)
    abuts_marsh_wetland: Mapped[bool | None] = mapped_column(nullable=True)
    abuts_park_public: Mapped[bool | None] = mapped_column(nullable=True)
    abuts_conservation_easement: Mapped[bool | None] = mapped_column(nullable=True)
    abuts_buildable_private: Mapped[bool | None] = mapped_column(nullable=True)
    rear_open_distance_ft: Mapped[float | None] = mapped_column(Float, nullable=True)
    wetland_pct_of_parcel: Mapped[float | None] = mapped_column(Float, nullable=True)
    flood_zone: Mapped[str | None] = mapped_column(String, nullable=True)

    # canopy
    parcel_canopy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    neighborhood_canopy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    canopy_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_year_built_buffer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canopy_age_proxy: Mapped[float | None] = mapped_column(Float, nullable=True)

    # road & position -- columns reserved now, populated once OSM
    # integration ships (deferred; see docs/FEATURE_SCHEMA.md §2.3)
    fronting_road_class: Mapped[str | None] = mapped_column(String, nullable=True)
    dist_to_arterial_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_cul_de_sac: Mapped[bool | None] = mapped_column(nullable=True)
    is_dead_end: Mapped[bool | None] = mapped_column(nullable=True)
    through_traffic_proxy: Mapped[float | None] = mapped_column(Float, nullable=True)
    front_setback_ft: Mapped[float | None] = mapped_column(Float, nullable=True)

    # structure & architecture -- vision-tagged fields populated lazily,
    # on first view, by canopy/vision.py (not the weekly bulk pass)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sqft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    beds: Mapped[float | None] = mapped_column(Float, nullable=True)
    baths: Mapped[float | None] = mapped_column(Float, nullable=True)
    stories: Mapped[float | None] = mapped_column(Float, nullable=True)
    # sqft/beds -- a crude but real proxy for room size, backs the
    # small_rooms/spacious_rooms tags (canopy/features.py)
    avg_room_sqft: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Recent year_built clustered with nearby listings' year_built (see
    # median_year_built_buffer below) -- a mass-built tract subdivision
    # signature, distinct from a lone custom new-build infill. Backs the
    # new_build tag and is eligible for canopy/model.py's veto mechanism,
    # not a hard filter (canopy/features.py has the full reasoning).
    is_tract_new_build: Mapped[bool | None] = mapped_column(nullable=True)
    arch_style: Mapped[str | None] = mapped_column(String, nullable=True)
    arch_style_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    exterior_material: Mapped[str | None] = mapped_column(String, nullable=True)
    has_front_porch: Mapped[bool | None] = mapped_column(nullable=True)
    garage_type: Mapped[str | None] = mapped_column(String, nullable=True)
    visible_renovation_recency: Mapped[str | None] = mapped_column(String, nullable=True)
    vision_computed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    # market
    list_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_per_sqft: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_on_market: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_cut_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hoa_fee_monthly: Mapped[float | None] = mapped_column(Float, nullable=True)

    # imputation tracking + escape hatch for experimental features before
    # they're promoted to real columns
    imputed_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)


class Anchor(Base):
    """A named place either rater cares about proximity to. One shared
    list -- either partner can add one, both see the same list."""

    __tablename__ = "anchors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)  # beach | grocery | social | work | school
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    # What Mapbox actually resolved the input address to -- shown back to
    # the rater so they can confirm the geocode, not just trust it (see
    # canopy/clients/mapbox.py's WILMINGTON_METRO_BBOX comment for why
    # that matters). Null for anchors created via direct lat/lon.
    resolved_address: Mapped[str | None] = mapped_column(String, nullable=True)
    ideal_minutes: Mapped[int] = mapped_column(Integer, default=15)
    limit_minutes: Mapped[int] = mapped_column(Integer, default=30)
    created_by: Mapped[str] = mapped_column(ForeignKey("raters.id"))
    active: Mapped[bool] = mapped_column(default=True)


class ListingAnchorTime(Base):
    """Drive time from a listing to an anchor. `is_proxy` stays True (a
    haversine-based estimate) until real routing backfills the row --
    see docs/FEATURE_SCHEMA.md §2.4 and the deferred-routing decision in
    the pivot plan."""

    __tablename__ = "listing_anchor_times"

    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), primary_key=True)
    anchor_id: Mapped[int] = mapped_column(ForeignKey("anchors.id"), primary_key=True)
    drive_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    straight_line_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_proxy: Mapped[bool] = mapped_column(default=True)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Rater(Base):
    __tablename__ = "raters"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # 'zach' | 'andrea'
    display_name: Mapped[str] = mapped_column(String)


class Judgment(Base):
    """A single Yes/No/Maybe verdict from one rater on one listing.
    Judgments accumulate as a log rather than upsert -- re-rating a
    listing later is expected (a 'yes' in March isn't the same bar as a
    'yes' in July), so there's no uniqueness constraint on (rater,
    listing)."""

    __tablename__ = "judgments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rater_id: Mapped[str] = mapped_column(ForeignKey("raters.id"))
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    mode: Mapped[str] = mapped_column(String)  # 'swipe' | 'detail'
    verdict: Mapped[str] = mapped_column(String)  # 'yes' | 'no' | 'maybe'
    session_id: Mapped[str] = mapped_column(String)
    feature_set_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Tag(Base):
    """Yes/No tag taxonomy. Tags never enter the feature vector -- they
    only shape the model's structure and priors (see SCORING_MODEL.md
    §4). `anchor_aware` tags (e.g. `too_far`, `well_placed`) prompt an
    optional follow-up asking which anchors were meant."""

    __tablename__ = "tags"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String)
    polarity: Mapped[str] = mapped_column(String)  # 'positive' | 'negative'
    mapped_features: Mapped[list] = mapped_column(JSON)
    anchor_aware: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)


class JudgmentTag(Base):
    __tablename__ = "judgment_tags"

    judgment_id: Mapped[int] = mapped_column(
        ForeignKey("judgments.id", ondelete="CASCADE"), primary_key=True
    )
    tag_code: Mapped[str] = mapped_column(ForeignKey("tags.code"), primary_key=True)
    free_text: Mapped[str | None] = mapped_column(String, nullable=True)  # other_yes / other_no only


class JudgmentAnchor(Base):
    """Optional anchor attribution on a judgment -- resolves which
    specific place a `well_placed`/`too_far` tag was about, so credit/
    blame doesn't have to be inferred from correlation across anchors."""

    __tablename__ = "judgment_anchors"

    judgment_id: Mapped[int] = mapped_column(
        ForeignKey("judgments.id", ondelete="CASCADE"), primary_key=True
    )
    anchor_id: Mapped[int] = mapped_column(ForeignKey("anchors.id"), primary_key=True)


class PairwiseComparison(Base):
    __tablename__ = "pairwise_comparisons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rater_id: Mapped[str] = mapped_column(ForeignKey("raters.id"))
    listing_a: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    listing_b: Mapped[str] = mapped_column(ForeignKey("listings.id"))
    winner: Mapped[str] = mapped_column(String)  # 'a' | 'b' | 'tie'
    selection_strategy: Mapped[str | None] = mapped_column(String, nullable=True)  # active | random | top_ranked
    feature_set_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class ModelRun(Base):
    """One fitted pairwise preference model for one rater. Coefficients
    are ridge-regularized toward the cold-start prior (canopy/model_prior.py),
    not toward zero -- see SCORING_MODEL.md §3."""

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rater_id: Mapped[str] = mapped_column(ForeignKey("raters.id"))
    feature_set_version: Mapped[str] = mapped_column(String)
    trained_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    n_pairs: Mapped[int] = mapped_column(Integer)
    coefficients: Mapped[dict] = mapped_column(JSON)  # {feature: weight}
    coef_ci: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {feature: [lo, hi]}, bootstrap
    scaler_params: Mapped[dict] = mapped_column(JSON)  # quantile/z params, for reproducibility
    basis_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # active hinge terms + vetoes
    holdout_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)  # price-only model


class PreferenceScore(Base):
    """Learned-model output for one listing under one model run. Distinct
    from `Score` (Stage 3's deterministic canopy %/old-growth-proxy
    numbers, which this table does not replace)."""

    __tablename__ = "preference_scores"

    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.id"), primary_key=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("model_runs.id"), primary_key=True)
    raw_score: Mapped[float] = mapped_column(Float)
    display_score: Mapped[float] = mapped_column(Float)  # 0-100, percentile-normalized
    pred_variance: Mapped[float | None] = mapped_column(Float, nullable=True)  # bootstrap variance
