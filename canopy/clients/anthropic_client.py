"""Anthropic API client for the Stage 5 sub-agent.

Deliberately narrow scope per docs/CLAUDE.md: vision sanity-check +
rationale synthesis on the already-filtered shortlist only. Not used for
any geometric/adjacency/canopy determination -- those are already decided
by Stages 2-4 and passed in here as structured facts.
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
