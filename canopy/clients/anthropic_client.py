"""Anthropic API client for the vision pass.

Deliberately narrow scope per docs/CLAUDE.md: structural/architecture
feature extraction + rationale synthesis, called lazily on first view of a
listing (see canopy/vision.py) -- not on the full weekly listing volume.
Geometric/adjacency values are still decided deterministically upstream
and passed in here as structured facts, never re-derived by this call.
The one deliberate exception is canopy: the raster (2021 NLCD) can be
badly stale (e.g. a recent clear-cut), so this call is explicitly asked
to compare the image against the raster's canopy_pct and report a
canopy_condition + its own corrected estimate; canopy/vision.py applies
that correction to a listing's effective canopy value only when the read
is high-confidence -- see CANOPY_OVERRIDE_CONFIDENCE_THRESHOLD there.
This call still never scores, ranks, or votes on overall preference --
SCORING_MODEL.md §10 is explicit that only rater judgments are training
labels.
"""

import base64
import json

import anthropic

from canopy.config import ANTHROPIC_API_KEY

MODEL = "claude-sonnet-5"

# The SDK's own default (per-request, including retries) is generous enough
# to outlast gunicorn's worker timeout on its own -- a single hung call took
# the whole worker down in production. This is a single-image classification
# call; it should complete in a few seconds, not minutes.
#
# 30s was still too generous: confirmed live that Railway's own edge proxy
# times out an upstream request at ~30s regardless of gunicorn's own (much
# longer) worker timeout, returning a synthetic 500 to the client while the
# backend keeps working unseen. /api/batch can attempt this call while
# building a response for a human waiting on it, so it needs real headroom
# under that ~30s ceiling, not just under gunicorn's.
REQUEST_TIMEOUT_SECONDS = 10.0

# The SDK retries up to twice by default (3 attempts total) *inside* a
# single .create() call, even with an explicit `timeout` set -- so a call
# that keeps timing out can still take ~3x REQUEST_TIMEOUT_SECONDS before
# raising. Confirmed live in production: a batch capped at 3 vision calls
# still blew past gunicorn's 120s worker timeout because one hung call
# alone could eat up to 90s. The caller (canopy/api.py's
# _try_ensure_vision) already treats any exception here as non-fatal --
# the listing just renders without vision fields -- so retrying here buys
# nothing but unbounded latency.
MAX_RETRIES = 0


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=MAX_RETRIES
    )


ARCH_STYLES = [
    "craftsman", "ranch", "coastal contemporary", "colonial revival",
    "cottage", "new traditional", "other",
]
GARAGE_TYPES = ["none", "attached", "detached", "carport"]
RENOVATION_RECENCY = ["original", "dated reno", "recent reno"]
CANOPY_CONDITIONS = ["consistent_with_raster", "recently_cleared", "significant_regrowth", "uncertain"]

STRUCTURAL_FEATURES_SCHEMA = {
    "type": "object",
    "properties": {
        "arch_style": {"type": "string", "enum": ARCH_STYLES},
        "arch_style_confidence": {
            "type": "number",
            "description": "0-1 confidence in the arch_style call, for down-weighting low-confidence tags during model fitting.",
        },
        "exterior_material": {
            "type": "string",
            "description": "Dominant visible exterior material, e.g. 'vinyl siding', 'brick', 'fiber cement', 'wood shingle'.",
        },
        "has_front_porch": {"type": "boolean"},
        "garage_type": {"type": "string", "enum": GARAGE_TYPES},
        "visible_renovation_recency": {"type": "string", "enum": RENOVATION_RECENCY},
        "rationale": {
            "type": "string",
            "description": "Plain-English writeup for the digest, 2-4 sentences, grounded in the structured signals and the image.",
        },
        "concerns": {
            "type": "string",
            "description": "Anything the image flags that the structured data missed (a 'marsh' that looks like a retention pond, active construction near protected land, etc., other than canopy condition, which is covered by canopy_condition below), or empty string.",
        },
        "canopy_condition": {
            "type": "string",
            "enum": CANOPY_CONDITIONS,
            "description": (
                "Compare the visible tree canopy on the LOT in the satellite/aerial "
                "image against parcel_canopy_pct in the structured facts (a 2021 "
                "raster number that can be stale). 'recently_cleared' = the image "
                "shows meaningfully LESS canopy than parcel_canopy_pct implies "
                "(e.g. cut for construction since the raster was captured). "
                "'significant_regrowth' = meaningfully MORE. 'consistent_with_raster' "
                "= roughly matches. 'uncertain' = image quality/angle can't tell. "
                "Judge this primarily from the aerial/satellite image, not the "
                "listing photo (which is ground-level and may not show the full lot)."
            ),
        },
        "canopy_condition_confidence": {
            "type": "number",
            "description": "0-1 confidence in canopy_condition, independent of arch_style_confidence.",
        },
        "corrected_canopy_pct_estimate": {
            "type": "number",
            "description": (
                "Your own visual estimate of current percent tree canopy cover on "
                "the lot, 0-100, from the aerial/satellite image. Always provide "
                "this regardless of canopy_condition -- used to track raster "
                "accuracy over time even when 'consistent_with_raster'."
            ),
        },
        "house_lot_summary": {
            "type": "string",
            "description": (
                "1-2 plain-English sentences for a rater actively deciding on this "
                "house right now, describing the house and lot from the image(s). "
                "Distinct from `rationale`, which is written for the weekly digest "
                "email, not the live rating screen -- no hedging/audit framing, "
                "write it like you're describing the property to a friend."
            ),
        },
    },
    "required": [
        "arch_style", "arch_style_confidence", "exterior_material", "has_front_porch",
        "garage_type", "visible_renovation_recency", "rationale", "concerns",
        "canopy_condition", "canopy_condition_confidence", "corrected_canopy_pct_estimate",
        "house_lot_summary",
    ],
    "additionalProperties": False,
}

STRUCTURAL_FEATURES_SYSTEM_PROMPT = (
    "You are assisting a personal real-estate scouting tool for Wilmington, NC. "
    "You are given one listing's structured signals (lot, canopy, adjacency, "
    "market data -- all already computed deterministically, not by you), its "
    "satellite/aerial image, and (when available) a recent listing photo from "
    "the Zillow marketing listing. The satellite image is the one comparable to "
    "the raster canopy measurement in the structured facts; the listing photo "
    "is ground-level and mainly useful for architecture/structure details and "
    "as a second, more recent, ground-truth check on visible tree cover near "
    "the house. Your job has three parts, and you do NOT rank, score, or "
    "express a preference on the listing in any part: "
    "(1) describe visible structural/architecture features from the image(s) -- "
    "style, exterior material, whether there's a front porch, garage type, and "
    "how recently the exterior looks renovated; "
    "(2) sanity-check the image(s) against the structured signals, flagging "
    "anything that looks wrong other than canopy condition (a 'marsh' that "
    "looks like a retention pond, active construction near land flagged as "
    "protected, etc.) as `concerns`, and separately judge `canopy_condition` -- "
    "the structured facts' parcel_canopy_pct comes from a 2021 satellite raster "
    "that can be badly stale (e.g. a lot clear-cut by a builder since then still "
    "shows high canopy), so compare what the image actually shows against that "
    "number and report a `corrected_canopy_pct_estimate` regardless of whether "
    "they agree; "
    "(3) write two distinct pieces of prose: `rationale`, a short plain-English "
    "writeup for a weekly digest EMAIL, in the style of: 'backs to a county-"
    "owned greenway, 78% canopy cover, neighboring parcel is a deeded "
    "conservation easement'; and `house_lot_summary`, a separate, warmer 1-2 "
    "sentence description for a rater looking at this listing live, right now, "
    "on the rating screen -- describe the property like you're describing it "
    "to a friend, not auditing it."
)


def extract_structural_features(
    structured_facts: dict,
    satellite_image_bytes: bytes,
    listing_photo_bytes: bytes | None = None,
) -> dict:
    """Lazy, per-listing call (see canopy/vision.py) -- extracts
    architecture/structure features, a canopy-condition read against the
    raster, and rationale/summary text. Returns a dict matching
    STRUCTURAL_FEATURES_SCHEMA. `listing_photo_bytes`, when given, is sent
    alongside the satellite image in the same call (no second API call) --
    a real, recent marketing photo is ground-truth for things the 2021
    raster can miss entirely."""
    satellite_b64 = base64.standard_b64encode(satellite_image_bytes).decode("utf-8")

    content = [
        {"type": "text", "text": "Satellite image (aerial view of the lot and surrounding parcels):"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": satellite_b64},
        },
    ]
    if listing_photo_bytes is not None:
        photo_b64 = base64.standard_b64encode(listing_photo_bytes).decode("utf-8")
        content += [
            {"type": "text", "text": "Listing photo (a recent marketing photo of the house, from the Zillow listing):"},
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": photo_b64},
            },
        ]
    content.append({
        "type": "text",
        "text": (
            "Structured signals for this listing:\n"
            + json.dumps(structured_facts, indent=2, default=str)
        ),
    })

    response = _client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=STRUCTURAL_FEATURES_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": STRUCTURAL_FEATURES_SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )

    # Structured JSON output can arrive split across multiple text content
    # blocks; taking only the first (via next()) silently truncated the
    # JSON mid-string on longer responses (observed in production: a
    # rationale long enough to spill into a second block).
    text = "".join(block.text for block in response.content if block.type == "text")
    return json.loads(text)
