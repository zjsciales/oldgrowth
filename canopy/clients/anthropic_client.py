"""Anthropic API client for the vision pass.

Deliberately narrow scope per docs/CLAUDE.md: structural/architecture
feature extraction + rationale synthesis, called lazily on first view of a
listing (see canopy/vision.py) -- not on the full weekly listing volume,
and never the primary geometric/adjacency/canopy determination (those are
already decided deterministically and passed in here as structured facts).
It also never scores, ranks, or votes on preference -- SCORING_MODEL.md
§10 is explicit that only rater judgments are training labels.
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
REQUEST_TIMEOUT_SECONDS = 30.0

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
            "description": "Anything the image flags that the structured data missed (recent clear-cutting, a 'marsh' that looks like a retention pond, etc.), or empty string.",
        },
    },
    "required": [
        "arch_style", "arch_style_confidence", "exterior_material", "has_front_porch",
        "garage_type", "visible_renovation_recency", "rationale", "concerns",
    ],
    "additionalProperties": False,
}

STRUCTURAL_FEATURES_SYSTEM_PROMPT = (
    "You are assisting a personal real-estate scouting tool for Wilmington, NC. "
    "You are given one listing's structured signals (lot, canopy, adjacency, "
    "market data -- all already computed deterministically, not by you) and its "
    "satellite image. Your job has two parts, and you do NOT rank, score, or "
    "express a preference on the listing either part: "
    "(1) describe visible structural/architecture features from the image -- "
    "style, exterior material, whether there's a front porch, garage type, and "
    "how recently the exterior looks renovated; "
    "(2) sanity-check the satellite image against the structured signals, "
    "flagging anything that looks wrong (recent clear-cutting, a 'marsh' that "
    "looks like a retention pond, active construction near land flagged as "
    "protected, etc.), and write a short plain-English rationale for a rating "
    "app, in the style of: 'backs to a county-owned greenway, 78% canopy cover, "
    "neighboring parcel is a deeded conservation easement.'"
)


def extract_structural_features(structured_facts: dict, satellite_image_bytes: bytes) -> dict:
    """Lazy, per-listing call (see canopy/vision.py) -- extracts
    architecture/structure features plus rationale text. Returns a dict
    matching STRUCTURAL_FEATURES_SCHEMA."""
    image_b64 = base64.standard_b64encode(satellite_image_bytes).decode("utf-8")

    response = _client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=STRUCTURAL_FEATURES_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": STRUCTURAL_FEATURES_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Structured signals for this listing:\n"
                            + json.dumps(structured_facts, indent=2, default=str)
                        ),
                    },
                ],
            }
        ],
    )

    # Structured JSON output can arrive split across multiple text content
    # blocks; taking only the first (via next()) silently truncated the
    # JSON mid-string on longer responses (observed in production: a
    # rationale long enough to spill into a second block).
    text = "".join(block.text for block in response.content if block.type == "text")
    return json.loads(text)
