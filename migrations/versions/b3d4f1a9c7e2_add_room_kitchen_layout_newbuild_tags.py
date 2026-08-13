"""add room_sizes/floor_plan/kitchen/new_build tags

Revision ID: b3d4f1a9c7e2
Revises: 341699da3cfb
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d4f1a9c7e2'
down_revision: Union[str, None] = '341699da3cfb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('listing_features', sa.Column('avg_room_sqft', sa.Float(), nullable=True))
    op.add_column('listing_features', sa.Column('is_tract_new_build', sa.Boolean(), nullable=True))

    _seed_tags()


# room_sizes/floor_plan/kitchen have no backing ListingFeatures column yet
# (no RentCast/GIS field exists for any of them, confirmed by a full-
# codebase search) -- seeded with mapped_features=[], same pattern as
# other_yes/other_no: real, votable tags that accumulate signal but don't
# yet drive hinge/threshold learning (FEATURE_SCHEMA.md §3.3: "recurring
# other_yes/other_no free text is a feature you haven't built yet").
# new_build maps to the new is_tract_new_build proxy (canopy/features.py)
# and has no positive counterpart -- an asymmetric near-certain-no signal,
# not a hard filter (see canopy/model.py's detect_vetoes, docs/CLAUDE.md).
tags_table = sa.table(
    "tags",
    sa.column("code", sa.String),
    sa.column("label", sa.String),
    sa.column("polarity", sa.String),
    sa.column("mapped_features", sa.JSON),
    sa.column("anchor_aware", sa.Boolean),
    sa.column("active", sa.Boolean),
)

NEG_TAGS = [
    ("small_rooms", "Rooms feel small", ["avg_room_sqft"], False),
    ("awkward_layout", "Awkward floor plan", [], False),
    ("dated_kitchen", "Kitchen needs work", [], False),
    ("new_build", "Feels like a tract/subdivision build", ["is_tract_new_build"], False),
]

POS_TAGS = [
    ("spacious_rooms", "Great room sizes", ["avg_room_sqft"], False),
    ("great_layout", "Great floor plan", [], False),
    ("great_kitchen", "Great kitchen", [], False),
]


def _seed_tags() -> None:
    op.bulk_insert(tags_table, [
        {"code": code, "label": label, "polarity": "negative",
         "mapped_features": features, "anchor_aware": anchor_aware, "active": True}
        for code, label, features, anchor_aware in NEG_TAGS
    ] + [
        {"code": code, "label": label, "polarity": "positive",
         "mapped_features": features, "anchor_aware": anchor_aware, "active": True}
        for code, label, features, anchor_aware in POS_TAGS
    ])


def downgrade() -> None:
    op.execute(
        "DELETE FROM tags WHERE code IN ("
        "'small_rooms', 'awkward_layout', 'dated_kitchen', 'new_build', "
        "'spacious_rooms', 'great_layout', 'great_kitchen'"
        ")"
    )
    op.drop_column('listing_features', 'is_tract_new_build')
    op.drop_column('listing_features', 'avg_room_sqft')
