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

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "flag_ok": {
            "type": "boolean",
            "description": (
                "True if the satellite image is consistent with the structured "
                "signals (still wooded, water/marsh look real, no recent "
                "clear-cutting). False if the image contradicts them."
            ),
        },
        "rationale": {
            "type": "string",
            "description": "Plain-English writeup for the digest, 2-4 sentences.",
        },
        "concerns": {
            "type": "string",
            "description": "Anything the image flags that the structured data missed, or empty string.",
        },
    },
    "required": ["flag_ok", "rationale", "concerns"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are assisting a personal real-estate scouting tool for Wilmington, NC. "
    "You are given a candidate listing that has already passed a deterministic "
    "rule-based filter (lot size, canopy %, adjacency flags) -- your job is NOT "
    "to redo that determination. Instead: (1) sanity-check the satellite image "
    "against the structured signals you're given, flagging anything that looks "
    "wrong (recent clear-cutting, a 'marsh' that looks like a retention pond, "
    "etc.), and (2) write a short plain-English rationale for a weekly email "
    "digest, in the style of: 'backs to a county-owned greenway, 78% canopy "
    "cover, neighboring parcel is a deeded conservation easement.'"
)


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def evaluate_candidate(structured_facts: dict, satellite_image_bytes: bytes) -> dict:
    """Runs the vision sanity-check + rationale synthesis for one candidate.

    Returns a dict matching RESULT_SCHEMA: {flag_ok, rationale, concerns}.
    """
    image_b64 = base64.standard_b64encode(satellite_image_bytes).decode("utf-8")

    response = _client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
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
                            "Structured signals for this candidate:\n"
                            + json.dumps(structured_facts, indent=2, default=str)
                        ),
                    },
                ],
            }
        ],
    )

    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


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

    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)
