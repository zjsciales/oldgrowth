"""Stage 4: the pairwise preference model. See docs/SCORING_MODEL.md for
the full design -- this is the concrete numpy/scipy implementation.

Deliberately not scikit-learn (SCORING_MODEL.md §10 rules out anything
fancier than an interpretable linear model at this data volume): ridge
toward a nonzero prior isn't an sklearn built-in anyway, so it's hand-
rolled either way.

Core model: P(a preferred to b) = sigmoid(w . (x_a - x_b)), fit by
minimizing pairwise log-loss plus a ridge penalty toward the cold-start
prior (not toward zero). Two raters get two entirely separate fits --
never averaged (SCORING_MODEL.md §5)."""

import logging
import random

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import norm, rankdata
from sqlalchemy.orm import Session

from canopy.db.models import (
    Anchor,
    Judgment,
    JudgmentAnchor,
    JudgmentTag,
    Listing,
    ListingFeatures,
    ModelRun,
    PairwiseComparison,
    PreferenceScore,
    Tag,
)
from canopy.features import FEATURE_SET_VERSION, anchor_rollups
from canopy.model_prior import COLD_START_PRIOR
from canopy.rating import excluded_listing_ids, ensure_anchor_times

logger = logging.getLogger(__name__)

# Real ListingFeatures columns used as numeric model inputs.
LISTING_FEATURES_NUMERIC_COLUMNS = [
    "lot_acreage", "lot_depth_ft", "lot_width_ft", "protected_perimeter_ratio",
    "rear_open_distance_ft", "wetland_pct_of_parcel", "parcel_canopy_pct",
    "neighborhood_canopy_pct", "canopy_delta", "median_year_built_buffer",
    "canopy_age_proxy", "dist_to_arterial_m", "through_traffic_proxy",
    "front_setback_ft", "year_built", "sqft", "beds", "baths", "stories",
    "list_price", "price_per_sqft", "days_on_market", "price_cut_count",
    "hoa_fee_monthly",
]
# Computed on the fly by canopy.features.anchor_rollups, not stored columns.
ANCHOR_ROLLUP_NAMES = ["min_drive_beach", "min_drive_grocery", "min_drive_work", "min_drive_school", "mean_drive_social"]
NUMERIC_FEATURES = LISTING_FEATURES_NUMERIC_COLUMNS + ANCHOR_ROLLUP_NAMES

BOOLEAN_FEATURES = [
    "abuts_water", "abuts_marsh_wetland", "abuts_park_public",
    "abuts_conservation_easement", "abuts_buildable_private",
    "is_cul_de_sac", "is_dead_end", "has_front_porch",
]
CATEGORICAL_FEATURES = [
    "flood_zone", "fronting_road_class", "arch_style",
    "exterior_material", "garage_type", "visible_renovation_recency",
]

RIDGE_LAMBDA0 = 5.0
RIDGE_N0 = 150
MAX_HINGE_TERMS = 6
HINGE_MIN_TAG_N = 10
HINGE_ASYMMETRY_THRESHOLD = 0.5
VETO_MIN_N = 10
VETO_MIN_FRACTION = 0.9
VETO_PENALTY = 5.0  # large but finite, in the same ~N(0,1) score units -- buries a listing without disappearing it
SWIPE_PAIRS_PER_SESSION_CAP = 20
HOLDOUT_FRACTION = 0.2
BOOTSTRAP_RESAMPLES = 200
MIN_PAIRS_FOR_HOLDOUT_EVAL = 10
MIN_DISAGREEMENT_FOR_DIGEST = 0.2  # z-score units -- excludes near-identical scores from the digest's disagreement section


class ModelError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Feature matrix assembly
# ---------------------------------------------------------------------------


def _raw_feature_row(session: Session, features: ListingFeatures) -> dict:
    row = {name: getattr(features, name, None) for name in LISTING_FEATURES_NUMERIC_COLUMNS}
    row.update(anchor_rollups(session, features.listing_id))
    for name in BOOLEAN_FEATURES:
        value = getattr(features, name, None)
        row[name] = (1.0 if value else 0.0) if value is not None else None
    for name in CATEGORICAL_FEATURES:
        row[name] = getattr(features, name, None)
    return row


def assemble_feature_matrix(
    session: Session, listings: list[ListingFeatures]
) -> tuple[np.ndarray, list[str], dict, list[str], list[dict]]:
    """Builds the base (non-hinge) design matrix for a population of
    listings: quantile-normalized numerics/booleans (rank transform, so
    outliers in price/acreage don't dominate) + one-hot categoricals.
    Missing numerics are median-imputed before normalizing (lands at
    z=0, i.e. "average," rather than distorting the rank order).

    Returns (X, feature_names, scaler_params, listing_ids, raw_rows) --
    raw_rows (unnormalized) is what hinge-threshold learning needs."""
    listing_ids = [f.listing_id for f in listings]
    raw_rows = [_raw_feature_row(session, f) for f in listings]

    columns: list[np.ndarray] = []
    names: list[str] = []
    scaler_params: dict = {}

    for name in NUMERIC_FEATURES + BOOLEAN_FEATURES:
        raw_values = np.array([row.get(name) for row in raw_rows], dtype=float)
        valid_mask = ~np.isnan(raw_values)
        if valid_mask.sum() == 0:
            columns.append(np.zeros(len(raw_rows)))
            names.append(name)
            scaler_params[name] = {"median_impute": None, "n": 0}
            continue

        median = float(np.median(raw_values[valid_mask]))
        filled = np.where(valid_mask, raw_values, median)
        ranks = rankdata(filled)
        z = norm.ppf((ranks - 0.5) / len(filled))

        columns.append(z)
        names.append(name)
        scaler_params[name] = {"median_impute": median, "n": int(valid_mask.sum())}

    for name in CATEGORICAL_FEATURES:
        categories = sorted({row.get(name) for row in raw_rows if row.get(name)})
        for category in categories:
            columns.append(np.array([1.0 if row.get(name) == category else 0.0 for row in raw_rows]))
            names.append(f"{name}={category}")

    X = np.column_stack(columns) if columns else np.zeros((len(raw_rows), 0))
    return X, names, scaler_params, listing_ids, raw_rows


# ---------------------------------------------------------------------------
# Tag-driven basis expansion (SCORING_MODEL.md §4)
# ---------------------------------------------------------------------------


def _resolve_mapped_features(
    session: Session, tag: Tag, judgment: Judgment, anchor_category_by_id: dict[int, str]
) -> list[str]:
    """Expands a tag's mapped_features, resolving the synthetic
    `anchor_drive_times` entry (too_far/well_placed) into concrete rollup
    feature names via judgment_anchors attribution (UI_SPEC.md §3.2).
    Unattributed anchor-aware judgments credit/blame every rollup
    equally -- a simplified stand-in for the doc's category-prior-
    weighted distribution."""
    if "anchor_drive_times" not in tag.mapped_features:
        return tag.mapped_features

    resolved = [f for f in tag.mapped_features if f != "anchor_drive_times"]
    attributed_ids = [
        ja.anchor_id for ja in session.query(JudgmentAnchor).filter_by(judgment_id=judgment.id)
    ]
    categories = {anchor_category_by_id[aid] for aid in attributed_ids if aid in anchor_category_by_id}
    if not categories:
        categories = {"beach", "grocery", "work", "school", "social"}
    resolved += [f"min_drive_{c}" for c in categories if c != "social"]
    if "social" in categories:
        resolved.append("mean_drive_social")
    return resolved


def classify_features_from_tags(session: Session, rater_id: str) -> dict[str, dict]:
    """Per SCORING_MODEL.md §4.1: classify each mapped feature as hygiene
    (only matters when bad), delighter (only matters when great), or
    linear, from Yes/No tag credit-blame asymmetry. n>=10 gate."""
    tag_rows = {t.code: t for t in session.query(Tag).all()}
    anchor_category_by_id = {a.id: a.category for a in session.query(Anchor).all()}

    credit: dict[str, int] = {}
    blame: dict[str, int] = {}

    rows = (
        session.query(JudgmentTag, Judgment)
        .join(Judgment, Judgment.id == JudgmentTag.judgment_id)
        .filter(Judgment.rater_id == rater_id)
        .all()
    )
    for jt, judgment in rows:
        tag = tag_rows.get(jt.tag_code)
        if tag is None:
            continue
        for feature_name in _resolve_mapped_features(session, tag, judgment, anchor_category_by_id):
            bucket = credit if judgment.verdict == "yes" else blame if judgment.verdict == "no" else None
            if bucket is not None:
                bucket[feature_name] = bucket.get(feature_name, 0) + 1

    classifications = {}
    for feature_name in set(credit) | set(blame):
        c, b = credit.get(feature_name, 0), blame.get(feature_name, 0)
        n = c + b
        asymmetry = (c - b) / n if n else 0.0
        if n < HINGE_MIN_TAG_N:
            kind = "linear"
        elif asymmetry <= -HINGE_ASYMMETRY_THRESHOLD:
            kind = "hygiene"
        elif asymmetry >= HINGE_ASYMMETRY_THRESHOLD:
            kind = "delighter"
        else:
            kind = "linear"
        classifications[feature_name] = {"credit": c, "blame": b, "n": n, "asymmetry": asymmetry, "kind": kind}

    return classifications


def learn_thresholds(
    session: Session, rater_id: str, feature_name: str, raw_rows: list[dict], listing_ids: list[str]
) -> tuple[float | None, float | None]:
    """tau_lo (dealbreaker: 75th pct of raw value among this rater's
    negative-tag listings) / tau_hi (delight boundary: 25th pct among
    positive-tag listings), per SCORING_MODEL.md §4.2."""
    raw_by_listing = dict(zip(listing_ids, raw_rows))
    tag_rows = {t.code: t for t in session.query(Tag).all()}
    anchor_category_by_id = {a.id: a.category for a in session.query(Anchor).all()}

    neg_values: list[float] = []
    pos_values: list[float] = []

    rows = (
        session.query(JudgmentTag, Judgment)
        .join(Judgment, Judgment.id == JudgmentTag.judgment_id)
        .filter(Judgment.rater_id == rater_id)
        .all()
    )
    for jt, judgment in rows:
        tag = tag_rows.get(jt.tag_code)
        if tag is None:
            continue
        if feature_name not in _resolve_mapped_features(session, tag, judgment, anchor_category_by_id):
            continue
        row = raw_by_listing.get(judgment.listing_id)
        if row is None:
            continue
        value = row.get(feature_name)
        if value is None:
            continue
        (neg_values if tag.polarity == "negative" else pos_values).append(value)

    tau_lo = float(np.percentile(neg_values, 75)) if neg_values else None
    tau_hi = float(np.percentile(pos_values, 25)) if pos_values else None
    return tau_lo, tau_hi


def _apply_hinge_config(hinge_config: dict, raw_rows: list[dict]) -> tuple[np.ndarray, list[str]]:
    columns = []
    names = []
    for col_name, info in hinge_config.items():
        feature_name = col_name.rsplit("__hinge_", 1)[0]
        raw_values = np.array([row.get(feature_name) for row in raw_rows], dtype=float)
        median = float(np.nanmedian(raw_values)) if not np.all(np.isnan(raw_values)) else 0.0
        filled = np.nan_to_num(raw_values, nan=median)
        if info["kind"] == "hygiene":
            col = np.maximum(0.0, info["tau_lo"] - filled)
        else:
            col = np.maximum(0.0, filled - info["tau_hi"])
        columns.append(col)
        names.append(col_name)
    X = np.column_stack(columns) if columns else np.zeros((len(raw_rows), 0))
    return X, names


def build_hinge_columns(
    session: Session, rater_id: str, classifications: dict, raw_rows: list[dict], listing_ids: list[str]
) -> tuple[np.ndarray, list[str], dict]:
    """Appends hinge-basis columns for hygiene/delighter-classified
    features, capped at MAX_HINGE_TERMS prioritized by tag volume."""
    candidates = [(name, info) for name, info in classifications.items() if info["kind"] in ("hygiene", "delighter")]
    candidates.sort(key=lambda item: item[1]["n"], reverse=True)

    hinge_config: dict = {}
    for feature_name, info in candidates[:MAX_HINGE_TERMS]:
        tau_lo, tau_hi = learn_thresholds(session, rater_id, feature_name, raw_rows, listing_ids)
        if info["kind"] == "hygiene" and tau_lo is not None:
            hinge_config[f"{feature_name}__hinge_lo"] = {"kind": "hygiene", "tau_lo": tau_lo, "n": info["n"]}
        if info["kind"] == "delighter" and tau_hi is not None:
            hinge_config[f"{feature_name}__hinge_hi"] = {"kind": "delighter", "tau_hi": tau_hi, "n": info["n"]}

    X_hinge, hinge_names = _apply_hinge_config(hinge_config, raw_rows)
    return X_hinge, hinge_names, hinge_config


# ---------------------------------------------------------------------------
# Near-deterministic vetoes (SCORING_MODEL.md §4.4)
# ---------------------------------------------------------------------------


def detect_vetoes(session: Session, rater_id: str, raw_rows: list[dict], listing_ids: list[str]) -> dict:
    """A feature VALUE present in >=90% of a rater's `no` judgments
    (n>=10) gets a large-but-finite score penalty at scoring time. Only
    meaningful for categorical/boolean features, where "value" is a
    discrete thing to threshold on."""
    raw_by_listing = dict(zip(listing_ids, raw_rows))
    no_judgments = session.query(Judgment).filter_by(rater_id=rater_id, verdict="no").all()
    if len(no_judgments) < VETO_MIN_N:
        return {}

    vetoes: dict = {}
    for feature_name in CATEGORICAL_FEATURES + BOOLEAN_FEATURES:
        counts: dict = {}
        total = 0
        for judgment in no_judgments:
            row = raw_by_listing.get(judgment.listing_id)
            if row is None:
                continue
            value = row.get(feature_name)
            if value is None:
                continue
            total += 1
            counts[value] = counts.get(value, 0) + 1
        if total < VETO_MIN_N:
            continue
        for value, count in counts.items():
            if count / total >= VETO_MIN_FRACTION:
                vetoes[feature_name] = {"value": value, "fraction": count / total, "n": total}
    return vetoes


# ---------------------------------------------------------------------------
# Training pairs (SCORING_MODEL.md §2)
# ---------------------------------------------------------------------------


def build_training_pairs(
    session: Session, rater_id: str, listing_id_to_row: dict[str, int]
) -> tuple[list[tuple[int, int]], list[int]]:
    """(index_pairs, y): y=1 always (the first index in each pair is the
    winner) -- explicit comparisons contribute one pair each (ties
    skipped); swipes become implicit pairs within a session (yes > maybe
    > no), capped at SWIPE_PAIRS_PER_SESSION_CAP sampled pairs/session so
    one big swipe batch can't dominate the loss."""
    index_pairs: list[tuple[int, int]] = []
    y: list[int] = []

    for comp in session.query(PairwiseComparison).filter_by(rater_id=rater_id).all():
        if comp.winner == "tie":
            continue
        idx_a = listing_id_to_row.get(comp.listing_a)
        idx_b = listing_id_to_row.get(comp.listing_b)
        if idx_a is None or idx_b is None:
            continue
        index_pairs.append((idx_a, idx_b) if comp.winner == "a" else (idx_b, idx_a))
        y.append(1)

    by_session: dict[str, list[Judgment]] = {}
    for j in session.query(Judgment).filter_by(rater_id=rater_id).all():
        by_session.setdefault(j.session_id, []).append(j)

    rank = {"yes": 2, "maybe": 1, "no": 0}
    rng = random.Random(0)  # fixed seed -- refits stay reproducible given the same judgment data
    for judgments in by_session.values():
        session_pairs = []
        for a in judgments:
            for b in judgments:
                if rank[a.verdict] <= rank[b.verdict]:
                    continue
                idx_a = listing_id_to_row.get(a.listing_id)
                idx_b = listing_id_to_row.get(b.listing_id)
                if idx_a is not None and idx_b is not None:
                    session_pairs.append((idx_a, idx_b))
        if len(session_pairs) > SWIPE_PAIRS_PER_SESSION_CAP:
            session_pairs = rng.sample(session_pairs, SWIPE_PAIRS_PER_SESSION_CAP)
        for idx_a, idx_b in session_pairs:
            index_pairs.append((idx_a, idx_b))
            y.append(1)

    return index_pairs, y


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------


def _nll_and_grad(w: np.ndarray, X_diff: np.ndarray, y: np.ndarray, w0: np.ndarray, lam: float):
    z = X_diff @ w
    p = expit(y * z)
    eps = 1e-12
    nll = -np.sum(np.log(np.clip(p, eps, 1.0)))
    grad_nll = -(X_diff * (y * (1 - p))[:, None]).sum(axis=0)
    reg = lam * np.sum((w - w0) ** 2)
    grad_reg = 2 * lam * (w - w0)
    return nll + reg, grad_nll + grad_reg


def fit_weights(X_diff: np.ndarray, y: np.ndarray, w0: np.ndarray, lam: float) -> np.ndarray:
    """minimize sum(log-loss(pairs)) + lam * ||w - w0||^2 -- ridge TOWARD
    the prior, not toward zero (SCORING_MODEL.md §3)."""
    if len(y) == 0:
        return w0.copy()
    result = minimize(_nll_and_grad, x0=w0, args=(X_diff, y, w0, lam), jac=True, method="L-BFGS-B")
    return result.x


def bootstrap_ci(
    X_diff: np.ndarray, y: np.ndarray, w0: np.ndarray, lam: float,
    n_resamples: int = BOOTSTRAP_RESAMPLES, seed: int | None = None,
) -> np.ndarray:
    """(n_resamples, n_features) array of bootstrap-refit coefficients.
    Callers derive coefficient CIs (percentiles) and per-listing
    pred_variance (score variance across resamples) from this."""
    if len(y) == 0:
        return np.tile(w0, (n_resamples, 1))
    rng = np.random.default_rng(seed)
    n = len(y)
    boot_weights = np.zeros((n_resamples, len(w0)))
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        boot_weights[i] = fit_weights(X_diff[idx], y[idx], w0, lam)
    return boot_weights


def _ridge_lambda(n_pairs: int) -> float:
    return RIDGE_LAMBDA0 / (1 + n_pairs / RIDGE_N0)


def fit_model(session: Session, rater_id: str) -> ModelRun:
    """Fits one rater's pairwise preference model against every listing
    with a computed feature vector, and persists a ModelRun. Does not
    write PreferenceScore rows -- call score_listings() with the result."""
    all_features = (
        session.query(ListingFeatures)
        .filter(ListingFeatures.feature_set_version == FEATURE_SET_VERSION)
        .all()
    )
    if not all_features:
        raise ModelError("no listings with computed features -- run compute-features first")

    for f in all_features:
        listing = session.get(Listing, f.listing_id)
        if listing is not None:
            ensure_anchor_times(session, listing)

    X_base, base_names, scaler_params, listing_ids, raw_rows = assemble_feature_matrix(session, all_features)
    listing_id_to_row = {lid: i for i, lid in enumerate(listing_ids)}

    classifications = classify_features_from_tags(session, rater_id)
    X_hinge, hinge_names, hinge_config = build_hinge_columns(session, rater_id, classifications, raw_rows, listing_ids)

    X_full = np.hstack([X_base, X_hinge]) if X_hinge.shape[1] else X_base
    feature_names = base_names + hinge_names
    w0 = np.array([COLD_START_PRIOR.get(name, 0.0) for name in feature_names])

    index_pairs, y_list = build_training_pairs(session, rater_id, listing_id_to_row)
    n_pairs = len(y_list)
    if n_pairs:
        X_diff = np.array([X_full[a] - X_full[b] for a, b in index_pairs])
        y = np.array(y_list, dtype=float)
    else:
        X_diff = np.zeros((0, len(feature_names)))
        y = np.array([])

    lam = _ridge_lambda(n_pairs)
    holdout_accuracy = None
    baseline_accuracy = None

    if n_pairs >= MIN_PAIRS_FOR_HOLDOUT_EVAL:
        rng = np.random.default_rng(0)
        idx = np.arange(n_pairs)
        rng.shuffle(idx)
        n_holdout = max(1, int(n_pairs * HOLDOUT_FRACTION))
        holdout_idx, train_idx = idx[:n_holdout], idx[n_holdout:]

        w_eval = fit_weights(X_diff[train_idx], y[train_idx], w0, lam)
        holdout_accuracy = float(np.mean(np.sign(X_diff[holdout_idx] @ w_eval) == y[holdout_idx]))

        if "price_per_sqft" in feature_names:
            price_idx = feature_names.index("price_per_sqft")
            w_baseline = fit_weights(
                X_diff[train_idx][:, [price_idx]], y[train_idx], np.array([0.0]), lam
            )
            baseline_accuracy = float(np.mean(
                np.sign(X_diff[holdout_idx][:, [price_idx]] @ w_baseline) == y[holdout_idx]
            ))

    w = fit_weights(X_diff, y, w0, lam)
    boot_weights = bootstrap_ci(X_diff, y, w0, lam, seed=0)
    coef_ci = {
        name: [float(np.percentile(boot_weights[:, i], 2.5)), float(np.percentile(boot_weights[:, i], 97.5))]
        for i, name in enumerate(feature_names)
    }

    vetoes = detect_vetoes(session, rater_id, raw_rows, listing_ids)

    model_run = ModelRun(
        rater_id=rater_id,
        feature_set_version=FEATURE_SET_VERSION,
        n_pairs=n_pairs,
        coefficients=dict(zip(feature_names, w.tolist())),
        coef_ci=coef_ci,
        scaler_params=scaler_params,
        basis_config={"hinges": hinge_config, "vetoes": vetoes},
        holdout_accuracy=holdout_accuracy,
        baseline_accuracy=baseline_accuracy,
    )
    session.add(model_run)
    session.commit()

    logger.info(
        "fit_model rater=%s n_pairs=%d holdout_acc=%s baseline_acc=%s hinges=%d vetoes=%d",
        rater_id, n_pairs, holdout_accuracy, baseline_accuracy, len(hinge_config), len(vetoes),
    )
    return model_run


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_listings(
    session: Session, model_run: ModelRun, listings: list[ListingFeatures] | None = None
) -> list[PreferenceScore]:
    """Scores listings under an already-fit ModelRun, writing
    PreferenceScore rows. Recomputes its own design matrix (base +
    stored hinge config) rather than reusing anything from fit_model --
    keeps this independently callable (e.g. re-scoring after new
    listings appear, without a full refit) at the cost of some redundant
    computation, which is cheap at this data volume."""
    if listings is None:
        listings = (
            session.query(ListingFeatures)
            .filter(ListingFeatures.feature_set_version == model_run.feature_set_version)
            .all()
        )
    if not listings:
        return []

    for f in listings:
        listing = session.get(Listing, f.listing_id)
        if listing is not None:
            ensure_anchor_times(session, listing)

    X_base, base_names, _scaler_params, listing_ids, raw_rows = assemble_feature_matrix(session, listings)
    hinge_config = (model_run.basis_config or {}).get("hinges", {})
    X_hinge, hinge_names = _apply_hinge_config(hinge_config, raw_rows)
    X_full = np.hstack([X_base, X_hinge]) if X_hinge.shape[1] else X_base
    feature_names = base_names + hinge_names

    w = np.array([model_run.coefficients.get(name, 0.0) for name in feature_names])
    raw_scores = X_full @ w

    vetoes = (model_run.basis_config or {}).get("vetoes", {})
    for i, row in enumerate(raw_rows):
        for feature_name, veto in vetoes.items():
            if row.get(feature_name) == veto["value"]:
                raw_scores[i] -= VETO_PENALTY

    pred_variance = _pred_variance(session, model_run, X_full, feature_names, listing_ids)

    if len(raw_scores) > 1:
        ranks = rankdata(raw_scores)
        display_scores = (ranks - 1) / (len(raw_scores) - 1) * 100
    else:
        display_scores = np.array([50.0] * len(raw_scores))

    results = []
    for i, listing_id in enumerate(listing_ids):
        score = (
            session.query(PreferenceScore)
            .filter_by(listing_id=listing_id, model_run_id=model_run.id)
            .one_or_none()
        )
        if score is None:
            score = PreferenceScore(listing_id=listing_id, model_run_id=model_run.id, raw_score=0, display_score=0)
            session.add(score)
        score.raw_score = float(raw_scores[i])
        score.display_score = float(display_scores[i])
        score.pred_variance = float(pred_variance[i])
        results.append(score)

    session.commit()
    logger.info("score_listings rater=%s model_run=%d n=%d", model_run.rater_id, model_run.id, len(results))
    return results


def _pred_variance(
    session: Session, model_run: ModelRun, X_full: np.ndarray, feature_names: list[str], listing_ids: list[str]
) -> np.ndarray:
    listing_id_to_row = {lid: i for i, lid in enumerate(listing_ids)}
    index_pairs, y_list = build_training_pairs(session, model_run.rater_id, listing_id_to_row)
    if not y_list:
        return np.zeros(len(listing_ids))

    X_diff = np.array([X_full[a] - X_full[b] for a, b in index_pairs])
    y = np.array(y_list, dtype=float)
    w0 = np.array([COLD_START_PRIOR.get(name, 0.0) for name in feature_names])
    lam = _ridge_lambda(len(y_list))
    boot_weights = bootstrap_ci(X_diff, y, w0, lam, seed=0)
    boot_scores = X_full @ boot_weights.T  # (n_listings, n_resamples)
    return boot_scores.var(axis=1)


# ---------------------------------------------------------------------------
# Weekly digest combination (SCORING_MODEL.md §5-6)
# ---------------------------------------------------------------------------


def _latest_model_run(session: Session, rater_id: str) -> ModelRun | None:
    return (
        session.query(ModelRun)
        .filter(ModelRun.rater_id == rater_id)
        .order_by(ModelRun.trained_at.desc())
        .first()
    )


def _latest_yes_tags(session: Session, rater_id: str, listing_id: str) -> set[str]:
    judgment = (
        session.query(Judgment)
        .filter_by(rater_id=rater_id, listing_id=listing_id, verdict="yes")
        .order_by(Judgment.created_at.desc())
        .first()
    )
    if judgment is None:
        return set()
    return {jt.tag_code for jt in session.query(JudgmentTag).filter_by(judgment_id=judgment.id)}


def compute_digest_slots(session: Session, rater_a_id: str, rater_b_id: str) -> dict:
    """Combines both raters' latest scores into the weekly digest plan.
    joint_score = min(z_a, z_b) -- NOT mean. A listing one of you loves
    and the other hates is not a good listing, and averaging hides
    exactly that (SCORING_MODEL.md §5). 70/20/10 top-ranked/uncertain/
    wildcard slot split per §6, so the model can't quietly narrow the
    search space the way the old hard filter did."""
    run_a = _latest_model_run(session, rater_a_id)
    run_b = _latest_model_run(session, rater_b_id)
    if run_a is None or run_b is None:
        return {"ready": False, "top_ranked": [], "uncertain": [], "wildcard": [], "disagreements": [], "same_verdict_different_tags": []}

    scores_a = {ps.listing_id: ps for ps in session.query(PreferenceScore).filter_by(model_run_id=run_a.id)}
    scores_b = {ps.listing_id: ps for ps in session.query(PreferenceScore).filter_by(model_run_id=run_b.id)}
    # Hard-no property types (e.g. Condo) must never reach the digest,
    # same as they're excluded from the rating UI's candidate queries --
    # see canopy/config.py's EXCLUDED_PROPERTY_TYPES.
    excluded_ids = excluded_listing_ids(session)
    common_ids = sorted((set(scores_a) & set(scores_b)) - excluded_ids)
    if not common_ids:
        return {"ready": False, "top_ranked": [], "uncertain": [], "wildcard": [], "disagreements": [], "same_verdict_different_tags": []}

    raw_a = np.array([scores_a[lid].raw_score for lid in common_ids])
    raw_b = np.array([scores_b[lid].raw_score for lid in common_ids])
    z_a = (raw_a - raw_a.mean()) / (raw_a.std() or 1.0)
    z_b = (raw_b - raw_b.mean()) / (raw_b.std() or 1.0)

    joint_score = np.minimum(z_a, z_b)
    agreement_score = (z_a + z_b) / 2
    disagreement = np.abs(z_a - z_b)
    variance = np.array([
        max(scores_a[lid].pred_variance or 0.0, scores_b[lid].pred_variance or 0.0) for lid in common_ids
    ])

    n = len(common_ids)
    order = np.argsort(-joint_score)
    n_top = max(1, round(n * 0.7))
    n_uncertain = max(1, round(n * 0.2)) if n > n_top else 0

    top_ids = [common_ids[i] for i in order[:n_top]]
    remaining = [i for i in order[n_top:]]
    remaining.sort(key=lambda i: -variance[i])
    uncertain_ids = [common_ids[i] for i in remaining[:n_uncertain]]

    used = set(top_ids) | set(uncertain_ids)
    wildcard_pool = [i for i in range(n) if common_ids[i] not in used]
    random.Random().shuffle(wildcard_pool)
    n_wildcard = max(0, n - len(used)) if n > len(used) else 0
    wildcard_ids = [common_ids[i] for i in wildcard_pool[:n_wildcard]]

    # MIN_DISAGREEMENT_FOR_DIGEST guards against the low-n case where
    # "rank by disagreement, cap at 10" would otherwise surface listings
    # both raters scored identically, just because there weren't 10
    # better candidates to fill the section with -- confirmed live: with
    # only 2 scored listings, an identical-score pair (disagreement=0.0)
    # showed up under "you two disagree about these."
    high_score_mask = (z_a > 0.5) | (z_b > 0.5)
    disagreement_order = sorted(range(n), key=lambda i: -disagreement[i])
    disagreement_ids = [
        common_ids[i] for i in disagreement_order
        if high_score_mask[i] and disagreement[i] > MIN_DISAGREEMENT_FOR_DIGEST
    ][:10]

    same_verdict_ids = []
    for listing_id in common_ids:
        tags_a = _latest_yes_tags(session, rater_a_id, listing_id)
        tags_b = _latest_yes_tags(session, rater_b_id, listing_id)
        if tags_a and tags_b and not (tags_a & tags_b):
            same_verdict_ids.append(listing_id)

    by_id = {lid: i for i, lid in enumerate(common_ids)}

    def _detail(listing_id: str) -> dict:
        i = by_id[listing_id]
        return {
            "listing_id": listing_id,
            "joint_score": float(joint_score[i]),
            "agreement_score": float(agreement_score[i]),
            "disagreement": float(disagreement[i]),
            "z_a": float(z_a[i]),
            "z_b": float(z_b[i]),
        }

    return {
        "ready": True,
        "top_ranked": [_detail(lid) for lid in top_ids],
        "uncertain": [_detail(lid) for lid in uncertain_ids],
        "wildcard": [_detail(lid) for lid in wildcard_ids],
        "disagreements": [_detail(lid) for lid in disagreement_ids],
        "same_verdict_different_tags": same_verdict_ids,
    }
