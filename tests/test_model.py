import itertools
import random

import numpy as np
import pytest

from canopy.db.models import Listing, ListingFeatures, ModelRun, PreferenceScore, Rater, Tag
from canopy.model import (
    bootstrap_ci,
    build_training_pairs,
    classify_features_from_tags,
    compute_digest_slots,
    detect_vetoes,
    fit_model,
    fit_weights,
    learn_thresholds,
    score_listings,
)
from canopy.rating import record_comparison, record_judgment


def _listing(listing_id, **overrides):
    defaults = dict(
        id=listing_id, formatted_address=f"{listing_id} Test St", city="Wilmington",
        state="NC", zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        price=500000, raw={},
    )
    defaults.update(overrides)
    return Listing(**defaults)


def _features(listing_id, **overrides):
    defaults = dict(listing_id=listing_id, feature_set_version="v1")
    defaults.update(overrides)
    return ListingFeatures(**defaults)


# ---------------------------------------------------------------------------
# fit_weights -- the core numerical guarantees
# ---------------------------------------------------------------------------


def test_fit_weights_returns_exactly_the_prior_with_zero_pairs():
    w0 = np.array([0.5, -0.3, 1.0])
    w = fit_weights(np.zeros((0, 3)), np.array([]), w0, lam=5.0)
    np.testing.assert_array_equal(w, w0)


def test_fit_weights_learns_correct_sign_from_separable_data():
    rng = np.random.default_rng(0)
    n = 200
    X_diff = rng.normal(size=(n, 1))
    y = np.sign(X_diff[:, 0])
    y[y == 0] = 1
    w = fit_weights(X_diff, y, w0=np.array([0.0]), lam=0.01)  # tiny ridge, let data dominate
    assert w[0] > 0.5


def test_fit_weights_ridge_pulls_toward_prior_at_low_n():
    # one single, noisy pair -- with a strong prior and a large lambda,
    # the fit shouldn't swing far from w0 based on one data point
    w0 = np.array([0.2])
    X_diff = np.array([[1.0]])
    y = np.array([1.0])
    w = fit_weights(X_diff, y, w0, lam=50.0)
    assert w[0] == pytest.approx(w0[0], abs=0.05)


def test_bootstrap_ci_width_shrinks_with_more_pairs():
    rng = np.random.default_rng(1)

    def ci_width(n_pairs):
        X_diff = rng.normal(size=(n_pairs, 1))
        y = np.sign(X_diff[:, 0] + rng.normal(scale=0.1, size=n_pairs))
        y[y == 0] = 1
        boot = bootstrap_ci(X_diff, y, np.array([0.0]), lam=1.0, n_resamples=50, seed=2)
        lo, hi = np.percentile(boot[:, 0], [2.5, 97.5])
        return hi - lo

    assert ci_width(300) < ci_width(20)


# ---------------------------------------------------------------------------
# Tag-driven basis expansion
# ---------------------------------------------------------------------------


def _seed_canopy_tags(session):
    session.add_all([
        Tag(code="lot_too_open", label="Lot too open", polarity="negative", mapped_features=["parcel_canopy_pct"]),
        Tag(code="mature_canopy", label="Beautiful trees", polarity="positive", mapped_features=["parcel_canopy_pct"]),
    ])


def test_classify_features_hygiene_when_mostly_blamed(session):
    session.add(Rater(id="zach", display_name="Zach"))
    _seed_canopy_tags(session)
    for i in range(11):
        session.add(_listing(f"l{i}"))
    session.commit()

    for i in range(10):
        record_judgment(session, rater_id="zach", listing_id=f"l{i}", mode="swipe", verdict="no", session_id=f"s{i}", tags=["lot_too_open"])
    record_judgment(session, rater_id="zach", listing_id="l10", mode="swipe", verdict="yes", session_id="s10", tags=["mature_canopy"])

    result = classify_features_from_tags(session, "zach")

    assert result["parcel_canopy_pct"]["kind"] == "hygiene"
    assert result["parcel_canopy_pct"]["n"] == 11


def test_classify_features_delighter_when_mostly_credited(session):
    session.add(Rater(id="zach", display_name="Zach"))
    _seed_canopy_tags(session)
    for i in range(11):
        session.add(_listing(f"l{i}"))
    session.commit()

    for i in range(10):
        record_judgment(session, rater_id="zach", listing_id=f"l{i}", mode="swipe", verdict="yes", session_id=f"s{i}", tags=["mature_canopy"])
    record_judgment(session, rater_id="zach", listing_id="l10", mode="swipe", verdict="no", session_id="s10", tags=["lot_too_open"])

    result = classify_features_from_tags(session, "zach")

    assert result["parcel_canopy_pct"]["kind"] == "delighter"


def test_classify_features_linear_below_n_gate(session):
    session.add(Rater(id="zach", display_name="Zach"))
    _seed_canopy_tags(session)
    for i in range(3):
        session.add(_listing(f"l{i}"))
    session.commit()

    for i in range(3):
        record_judgment(session, rater_id="zach", listing_id=f"l{i}", mode="swipe", verdict="no", session_id=f"s{i}", tags=["lot_too_open"])

    result = classify_features_from_tags(session, "zach")

    # only 3 judgments -- below HINGE_MIN_TAG_N=10, even though 100% blame
    assert result["parcel_canopy_pct"]["kind"] == "linear"


def test_learn_thresholds_matches_hand_computed_percentiles(session):
    session.add(Rater(id="zach", display_name="Zach"))
    _seed_canopy_tags(session)
    neg_values = [10, 20, 30, 40, 50]
    pos_values = [60, 70, 80, 90, 100]
    listing_ids = []
    raw_rows = []
    for i, v in enumerate(neg_values):
        session.add(_listing(f"neg{i}"))
    for i, v in enumerate(pos_values):
        session.add(_listing(f"pos{i}"))
    session.commit()

    for i, v in enumerate(neg_values):
        record_judgment(session, rater_id="zach", listing_id=f"neg{i}", mode="swipe", verdict="no", session_id=f"sn{i}", tags=["lot_too_open"])
        listing_ids.append(f"neg{i}")
        raw_rows.append({"parcel_canopy_pct": v})
    for i, v in enumerate(pos_values):
        record_judgment(session, rater_id="zach", listing_id=f"pos{i}", mode="swipe", verdict="yes", session_id=f"sp{i}", tags=["mature_canopy"])
        listing_ids.append(f"pos{i}")
        raw_rows.append({"parcel_canopy_pct": v})

    tau_lo, tau_hi = learn_thresholds(session, "zach", "parcel_canopy_pct", raw_rows, listing_ids)

    assert tau_lo == pytest.approx(np.percentile(neg_values, 75))
    assert tau_hi == pytest.approx(np.percentile(pos_values, 25))


# ---------------------------------------------------------------------------
# Training pairs
# ---------------------------------------------------------------------------


def test_build_training_pairs_from_explicit_comparisons(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add_all([_listing("l1"), _listing("l2")])
    session.commit()
    record_comparison(session, rater_id="zach", listing_a="l1", listing_b="l2", winner="a")

    index_pairs, y = build_training_pairs(session, "zach", {"l1": 0, "l2": 1})

    assert index_pairs == [(0, 1)]
    assert y == [1]


def test_build_training_pairs_ties_are_skipped(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add_all([_listing("l1"), _listing("l2")])
    session.commit()
    record_comparison(session, rater_id="zach", listing_a="l1", listing_b="l2", winner="tie")

    index_pairs, y = build_training_pairs(session, "zach", {"l1": 0, "l2": 1})

    assert index_pairs == []


def test_build_training_pairs_swipe_session_ranks_yes_over_no(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add_all([_listing("l1"), _listing("l2")])
    session.commit()
    record_judgment(session, rater_id="zach", listing_id="l1", mode="swipe", verdict="yes", session_id="s1")
    record_judgment(session, rater_id="zach", listing_id="l2", mode="swipe", verdict="no", session_id="s1")

    index_pairs, y = build_training_pairs(session, "zach", {"l1": 0, "l2": 1})

    assert index_pairs == [(0, 1)]


def test_build_training_pairs_caps_pairs_per_session(session):
    session.add(Rater(id="zach", display_name="Zach"))
    n = 10  # 5 yes, 5 no -> 25 possible yes>no pairs, capped at 20
    for i in range(n):
        session.add(_listing(f"l{i}"))
    session.commit()
    for i in range(n):
        verdict = "yes" if i < 5 else "no"
        record_judgment(session, rater_id="zach", listing_id=f"l{i}", mode="swipe", verdict=verdict, session_id="s1")

    listing_id_to_row = {f"l{i}": i for i in range(n)}
    index_pairs, y = build_training_pairs(session, "zach", listing_id_to_row)

    assert len(index_pairs) == 20


# ---------------------------------------------------------------------------
# Vetoes
# ---------------------------------------------------------------------------


def test_detect_vetoes_flags_near_unanimous_rejection_value(session):
    session.add(Rater(id="zach", display_name="Zach"))
    for i in range(10):
        session.add(_listing(f"l{i}"))
    session.commit()
    listing_ids = [f"l{i}" for i in range(10)]
    raw_rows = [{"flood_zone": "VE"} for _ in range(9)] + [{"flood_zone": "X"}]
    for i in range(10):
        record_judgment(session, rater_id="zach", listing_id=f"l{i}", mode="swipe", verdict="no", session_id=f"s{i}")

    vetoes = detect_vetoes(session, "zach", raw_rows, listing_ids)

    assert vetoes["flood_zone"]["value"] == "VE"
    assert vetoes["flood_zone"]["fraction"] == pytest.approx(0.9)


def test_detect_vetoes_empty_below_n_gate(session):
    session.add(Rater(id="zach", display_name="Zach"))
    for i in range(3):
        session.add(_listing(f"l{i}"))
    session.commit()
    for i in range(3):
        record_judgment(session, rater_id="zach", listing_id=f"l{i}", mode="swipe", verdict="no", session_id=f"s{i}")

    vetoes = detect_vetoes(session, "zach", [{"flood_zone": "VE"}] * 3, [f"l{i}" for i in range(3)])

    assert vetoes == {}


# ---------------------------------------------------------------------------
# fit_model / score_listings integration
# ---------------------------------------------------------------------------


def test_fit_model_raises_without_any_features(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()

    from canopy.model import ModelError
    with pytest.raises(ModelError):
        fit_model(session, "zach")


def test_fit_model_and_score_listings_end_to_end(session):
    session.add(Rater(id="zach", display_name="Zach"))
    n = 16
    for i in range(n):
        canopy = 10.0 + i * 5  # 10..85, strictly increasing with index
        session.add(_listing(f"l{i}", price=500000))
        session.add(_features(f"l{i}", parcel_canopy_pct=canopy, price_per_sqft=200.0))
    session.commit()

    # rater strictly prefers higher canopy -- higher index always wins
    rng = random.Random(0)
    pairs = list(itertools.combinations(range(n), 2))
    rng.shuffle(pairs)
    for i, j in pairs[:40]:
        hi, lo = (i, j) if i > j else (j, i)
        record_comparison(session, rater_id="zach", listing_a=f"l{hi}", listing_b=f"l{lo}", winner="a")

    model_run = fit_model(session, "zach")

    assert model_run.n_pairs == 40
    assert model_run.coefficients["parcel_canopy_pct"] > 0
    assert model_run.holdout_accuracy is not None
    assert model_run.holdout_accuracy > 0.6  # should clearly beat a coin flip

    scores = score_listings(session, model_run)
    scores_by_listing = {s.listing_id: s.raw_score for s in scores}
    assert scores_by_listing["l15"] > scores_by_listing["l0"]  # highest canopy scores higher than lowest

    # idempotent: re-scoring updates in place, not duplicate rows
    score_listings(session, model_run)
    assert session.query(PreferenceScore).filter_by(model_run_id=model_run.id).count() == n


# ---------------------------------------------------------------------------
# Digest slot combination -- min, not mean
# ---------------------------------------------------------------------------


def test_compute_digest_slots_not_ready_without_both_models(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()

    plan = compute_digest_slots(session, "zach", "andrea")

    assert plan["ready"] is False


def test_compute_digest_slots_uses_min_not_mean(session):
    session.add_all([Rater(id="zach", display_name="Zach"), Rater(id="andrea", display_name="Andrea")])
    for i in range(4):
        session.add(_listing(f"l{i}"))
    session.commit()
    run_a = ModelRun(rater_id="zach", feature_set_version="v1", n_pairs=0, coefficients={}, scaler_params={})
    run_b = ModelRun(rater_id="andrea", feature_set_version="v1", n_pairs=0, coefficients={}, scaler_params={})
    session.add_all([run_a, run_b])
    session.commit()

    # l0: both love it. l1: zach loves it, partner hates it (disagreement).
    # l2: both neutral. l3: both dislike it.
    session.add_all([
        PreferenceScore(listing_id="l0", model_run_id=run_a.id, raw_score=2.0, display_score=90, pred_variance=0.1),
        PreferenceScore(listing_id="l0", model_run_id=run_b.id, raw_score=2.0, display_score=90, pred_variance=0.1),
        PreferenceScore(listing_id="l1", model_run_id=run_a.id, raw_score=2.0, display_score=90, pred_variance=0.1),
        PreferenceScore(listing_id="l1", model_run_id=run_b.id, raw_score=-2.0, display_score=10, pred_variance=0.1),
        PreferenceScore(listing_id="l2", model_run_id=run_a.id, raw_score=0.0, display_score=50, pred_variance=0.1),
        PreferenceScore(listing_id="l2", model_run_id=run_b.id, raw_score=0.0, display_score=50, pred_variance=0.1),
        PreferenceScore(listing_id="l3", model_run_id=run_a.id, raw_score=-1.0, display_score=30, pred_variance=0.1),
        PreferenceScore(listing_id="l3", model_run_id=run_b.id, raw_score=-1.0, display_score=30, pred_variance=0.1),
    ])
    session.commit()

    plan = compute_digest_slots(session, "zach", "andrea")

    all_details = plan["top_ranked"] + plan["uncertain"] + plan["wildcard"]
    joint_by_id = {d["listing_id"]: d["joint_score"] for d in all_details}
    # l1 has a high agreement_score-style average (one rater loves it) but
    # min() must still rank it below the neutral, fully-agreed-on l2 --
    # this is the exact case "mean" would get wrong.
    assert joint_by_id["l1"] < joint_by_id["l2"]


def test_compute_digest_slots_excludes_near_identical_scores_from_disagreements(session):
    # confirmed live: with few scored listings, "rank by disagreement,
    # cap at 10" would otherwise surface a listing both raters scored
    # identically, just because there weren't 10 better candidates.
    session.add_all([Rater(id="zach", display_name="Zach"), Rater(id="andrea", display_name="Andrea")])
    session.add_all([_listing("l0"), _listing("l1")])
    session.commit()
    run_a = ModelRun(rater_id="zach", feature_set_version="v1", n_pairs=0, coefficients={}, scaler_params={})
    run_b = ModelRun(rater_id="andrea", feature_set_version="v1", n_pairs=0, coefficients={}, scaler_params={})
    session.add_all([run_a, run_b])
    session.commit()
    session.add_all([
        PreferenceScore(listing_id="l0", model_run_id=run_a.id, raw_score=1.0, display_score=90, pred_variance=0.1),
        PreferenceScore(listing_id="l0", model_run_id=run_b.id, raw_score=1.0, display_score=90, pred_variance=0.1),
        PreferenceScore(listing_id="l1", model_run_id=run_a.id, raw_score=0.5, display_score=50, pred_variance=0.1),
        PreferenceScore(listing_id="l1", model_run_id=run_b.id, raw_score=0.5, display_score=50, pred_variance=0.1),
    ])
    session.commit()

    plan = compute_digest_slots(session, "zach", "andrea")

    assert plan["disagreements"] == []


def test_compute_digest_slots_flags_same_verdict_different_tags(session):
    session.add_all([Rater(id="zach", display_name="Zach"), Rater(id="andrea", display_name="Andrea")])
    session.add(Tag(code="mature_canopy", label="Trees", polarity="positive", mapped_features=[]))
    session.add(Tag(code="water_adjacency", label="Water", polarity="positive", mapped_features=[]))
    session.add(_listing("l0"))
    session.commit()
    run_a = ModelRun(rater_id="zach", feature_set_version="v1", n_pairs=0, coefficients={}, scaler_params={})
    run_b = ModelRun(rater_id="andrea", feature_set_version="v1", n_pairs=0, coefficients={}, scaler_params={})
    session.add_all([run_a, run_b])
    session.commit()
    session.add_all([
        PreferenceScore(listing_id="l0", model_run_id=run_a.id, raw_score=1.0, display_score=80, pred_variance=0.1),
        PreferenceScore(listing_id="l0", model_run_id=run_b.id, raw_score=1.0, display_score=80, pred_variance=0.1),
    ])
    session.commit()
    record_judgment(session, rater_id="zach", listing_id="l0", mode="swipe", verdict="yes", session_id="s1", tags=["mature_canopy"])
    record_judgment(session, rater_id="andrea", listing_id="l0", mode="swipe", verdict="yes", session_id="s2", tags=["water_adjacency"])

    plan = compute_digest_slots(session, "zach", "andrea")

    assert "l0" in plan["same_verdict_different_tags"]
