import json
from dataclasses import dataclass

from canopy.clients.anthropic_client import extract_structural_features

FAKE_RESULT = {
    "arch_style": "coastal contemporary",
    "arch_style_confidence": 0.8,
    "exterior_material": "fiber cement",
    "has_front_porch": True,
    "garage_type": "attached",
    "visible_renovation_recency": "recent reno",
    "rationale": "Backs to marsh, 65% canopy.",
    "concerns": "",
}


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


class _FakeMessages:
    def __init__(self, blocks):
        self._blocks = blocks

    def create(self, **kwargs):
        return type("Response", (), {"content": self._blocks})()


class _FakeClient:
    def __init__(self, blocks):
        self.messages = _FakeMessages(blocks)


def test_extract_structural_features_joins_multiple_text_blocks(monkeypatch):
    """A structured JSON response split across multiple text content
    blocks must be concatenated, not truncated at the first block --
    production hit an "Unterminated string" JSONDecodeError from exactly
    this (a rationale long enough to spill into a second block)."""
    body = json.dumps(FAKE_RESULT)
    split_at = len(body) // 2
    blocks = [_TextBlock(body[:split_at]), _TextBlock(body[split_at:])]
    monkeypatch.setattr(
        "canopy.clients.anthropic_client._client", lambda: _FakeClient(blocks)
    )

    result = extract_structural_features({}, b"fake-image-bytes")

    assert result == FAKE_RESULT


def test_extract_structural_features_single_text_block(monkeypatch):
    blocks = [_TextBlock(json.dumps(FAKE_RESULT))]
    monkeypatch.setattr(
        "canopy.clients.anthropic_client._client", lambda: _FakeClient(blocks)
    )

    result = extract_structural_features({}, b"fake-image-bytes")

    assert result == FAKE_RESULT
