# SCORING_MODEL.md — Canopy Preference Model

How the features in `FEATURE_SCHEMA.md` become a weekly ranked shortlist,
and how the model learns from Yes/No judgments and their tags.

---

## 1. Design constraints

- **Data volume is small.** A few hundred judgments across two raters, ~30
  features. This is firmly linear-model territory. Anything fancier will
  memorize noise and be unreadable when it does.
- **Interpretability is a requirement, not a nice-to-have.** The coefficient
  vector *is* the "what we actually want in a house" dashboard, and reading
  it is half the value of the project.
- **Rank, never eliminate.** The prior version failed by hard-filtering to 2
  of 1025. Nothing in this model removes a listing from consideration; bad
  features cost rank.

---

## 2. Unified pairwise formulation

Both input types collapse into the same training signal: **preference pairs**.

- **Explicit comparisons** → one pair each, directly.
- **Swipes** → implicit pairs. Within a session, every `yes` outranks every
  `no`. Cap at ~20 sampled pairs per session so a single big swipe batch
  can't dominate the loss. `maybe` sits between: `yes > maybe > no`.

Model:

```
P(a preferred to b) = σ( w · (x_a − x_b) )
```

Logistic regression on feature *differences*, no intercept. Score for any
listing is then `s(x) = w · x`.

Why pairwise rather than yes/no classification: it's robust to the two of you
drifting in strictness over time (a "yes" in March and a "yes" in July aren't
the same bar), and it matches how you'll actually use the output — a ranking.

---

## 3. Training objective

```
minimize  Σ log-loss(pairs)  +  λ · ||w − w₀||²
```

- `w₀` = cold-start prior from stated preferences (§7).
- Ridge **toward the prior**, not toward zero, so early rankings are sensible
  and the model migrates off your stated preferences as evidence accumulates.
- Decay the prior's grip as data grows: `λ = λ₀ / (1 + n_pairs / n₀)`, with
  `n₀ ≈ 150` as a starting point.

Feature preprocessing: quantile-normalize numerics (robust to the price and
acreage outliers Wilmington will throw at you); one-hot categoricals; store
all scaler params in `model_runs.scaler_params` for reproducibility.

---

## 4. Tag-driven basis expansion

This is where Yes-tags and No-tags do their work. **Tags never enter the
feature vector** — they only decide the model's shape and priors.

### 4.1 Classify each feature

For feature `f`, over all judgments:

```
blame(f)  = # of No-tags mapped to f
credit(f) = # of Yes-tags mapped to f
asymmetry(f) = (credit − blame) / (credit + blame)
```

| Condition | Interpretation | Model treatment |
|---|---|---|
| `asymmetry < −0.5`, n ≥ 10 | **Hygiene** — only matters when bad | Add hinge penalty `max(0, τ_lo − f)` |
| `asymmetry > +0.5`, n ≥ 10 | **Delighter** — only matters when great | Add hinge bonus `max(0, f − τ_hi)` |
| otherwise | Linear | Plain term, no expansion |

Only expand features that clear the n ≥ 10 bar. Guard the total: cap active
hinge terms at ~6, prioritized by tag volume, or you'll reintroduce the
overfitting the linear model was chosen to avoid.

### 4.2 Learn the thresholds from tags

Don't hand-pick `τ_lo` / `τ_hi` — read them off the tag data:

- `τ_lo` = 75th percentile of `f` among listings tagged with `f`'s negative
  tag. (Above that, the tag mostly stops firing → that's the pain boundary.)
- `τ_hi` = 25th percentile of `f` among listings tagged with `f`'s positive
  tag. (Below that, the tag mostly stops firing → that's the delight
  boundary.)

**This is the answer to "what canopy number are we comfortable with."** After
~30 tagged rejections you'll have an empirical dealbreaker threshold for
`effective_canopy_pct`, and separately a delight threshold — and they'll almost
certainly differ, which is exactly why one hand-set number failed.

Same mechanism resolves "how old is old growth" via
`median_year_built_buffer`.

### 4.3 Tags as coefficient priors

Features with high tag volume in either direction get a weaker ridge pull
toward zero — you've demonstrated they matter, so let the data move them
freely. Features never mentioned in any tag stay tightly regularized. At low
n this meaningfully improves stability.

### 4.4 Near-deterministic vetoes

If a feature value is present in ≥90% of a rater's rejections and ≥10 cases
(e.g. `flood_zone = VE`), apply a **large but finite** penalty — big enough
to bury the listing, not so big it disappears. It still surfaces in the
exploration slots (§6), so a genuine exception can still reach you. Log these
in `model_runs.basis_config` and review them; a learned veto you disagree with
on sight is a useful signal in itself.

---

## 5. Two raters

Fit **separate models** per rater. Never average the judgments into one
model — that's how you converge on houses neither of you wants.

Combining for the weekly digest:

```
joint_score = min( z(s_zach), z(s_wife) )
```

Min, not mean. A house purchase requires both of you to be happy; a listing
one of you loves and the other hates is not a good listing, and averaging
hides exactly that. Percentile-normalize each rater's scores before combining
so different score scales don't let one of you dominate.

Also compute and surface:

- `agreement_score` = mean of the two z-scores
- `disagreement` = |z_zach − z_wife|

Digest gets a dedicated **"You two disagree about these"** section, ranked by
`disagreement` among listings where at least one score is high. Those are the
most productive conversations available to you in this whole process — the
model can't resolve a real difference in taste, only locate it.

Also worth flagging: listings both rate Yes but with *different tags*.
Agreement for different reasons is fragile agreement.

---

## 6. What goes in the weekly digest

Fixed slots, deliberately not all top-ranked:

| Slot | Share | Selection |
|---|---|---|
| Top ranked | ~70% | Highest `joint_score` |
| Uncertain | ~20% | Highest `pred_variance` across bootstrap models — the listings the model can't call, which are also the most informative to rate |
| Wildcard | ~10% | Random or deliberately off-profile |

The bottom two rows are the direct antidote to how you got to 2-of-1025.
Without them the model narrows confidently and you never find out about the
neighborhood you'd have loved but never searched.

For the pairwise UI, use **active selection**: pick pairs where predicted
`P ≈ 0.5` *and* bootstrap models disagree. Those pairs are worth several
times a random pair in information terms — meaningful when the two of you
only have the patience for a few dozen comparisons a week.

---

## 7. Cold start

1. Hand-set `w₀` from your current stated preferences (canopy matters a lot,
   protected rear matters a lot, price moderately, etc.). This is the only
   time stated preferences enter the system.
2. Run a **calibration session**: ~40 swipes each over a stratified sample
   spanning the whole market, not just plausible candidates. Stratify across
   canopy, lot size, price, and road class so early data covers the space
   instead of clustering.
3. Then ~20 active pairwise comparisons each.
4. Refit. Expect the coefficients to look different from `w₀` — that's the
   system working, not a bug.

---

## 8. Evaluation & trust

- **Hold out 20% of pairs.** Report pairwise accuracy on the holdout.
- **Baseline: price-only model.** If the full model can't beat "cheaper house
  wins," it's learned nothing and something upstream is broken.
- **Bootstrap CIs on every coefficient** (200 resamples). Display them in the
  weights dashboard — a coefficient whose CI spans zero should be shown as
  "not enough data yet," not as a finding.
- **Trust threshold:** ~150 pairs per rater before taking the coefficients
  seriously. Below that, treat the ranking as a prior-driven suggestion.
- **Refit cadence:** weekly, after each rating session, before the digest.

---

## 9. The weights dashboard

Simple page, but it's arguably the real product:

- Each feature's coefficient, per rater, side by side, with CIs.
- Learned thresholds (`τ_lo` / `τ_hi`) with the tag-count evidence behind them.
- Features classified hygiene / delighter / linear.
- Active vetoes.
- Holdout accuracy vs. price baseline, and pairs-collected progress.

Two people finding out they disagree about main-street proximity — with the
evidence in front of them — is worth more than any individual shortlist the
system produces.

---

## 10. Deliberately not doing

- Gradient boosting / random forests — will overfit at this n and destroy
  interpretability.
- Embedding-based similarity — no, and it hides the reasoning.
- Learning from the LLM's opinions about listings. The sub-agent explains and
  sanity-checks; it does not vote. Your judgments are the only labels.
- Per-listing free-text sentiment analysis. The tag taxonomy exists so the
  signal is structured; free text is for discovering missing features, not
  for fitting.

---

## Implementation notes (2026-08-12)

- **Concrete constants** (starting points, all in `canopy/model.py`):
  `RIDGE_LAMBDA0=5.0`, `RIDGE_N0=150` (§3's decay schedule),
  `MAX_HINGE_TERMS=6`, `HINGE_MIN_TAG_N=10`, `HINGE_ASYMMETRY_THRESHOLD
  =0.5` (§4.1), `VETO_MIN_N=10`, `VETO_MIN_FRACTION=0.9`, `VETO_PENALTY
  =5.0` (§4.4), `SWIPE_PAIRS_PER_SESSION_CAP=20` (§2),
  `HOLDOUT_FRACTION=0.2`, `BOOTSTRAP_RESAMPLES=200` (§8),
  `MIN_PAIRS_FOR_HOLDOUT_EVAL=10`.
- **`MIN_DISAGREEMENT_FOR_DIGEST=0.2`** (z-score units) — a genuine
  addition this doc didn't specify. §6's "ranked by disagreement, among
  listings where at least one score is high" has no lower bound, and at
  low listing counts that surfaced a listing both raters scored
  *identically* in the "you two disagree about these" section, just
  because there weren't 10 better candidates to fill it with. Found live,
  fixed with this threshold.
- **Fitting**: `scipy.optimize.minimize` (L-BFGS-B) on hand-derived
  log-loss + ridge gradients, exactly as sketched informally during
  planning — no deviation from the described objective.
- **`anchor_drive_times` tag resolution** (§4, via `UI_SPEC.md` §3.2):
  attributed judgments (via `judgment_anchors`) credit/blame the specific
  anchor's rollup feature; unattributed anchor-aware judgments distribute
  credit/blame equally across all five rollup features (§2.4 of
  `FEATURE_SCHEMA.md`) — a simplified stand-in for this doc's
  category-prior-weighted distribution, which isn't implemented.
- **`score_listings` recomputes its own bootstrap independently of
  `fit_model`'s bootstrap** — an intentional tradeoff so the two
  functions stay independently callable/testable (e.g. re-scoring
  without a full refit), at roughly 2x the bootstrap compute per weekly
  run. Fine at current data volume; see `ARCHITECTURE.md`'s Known
  Limitations if judgment counts grow large enough to matter.
