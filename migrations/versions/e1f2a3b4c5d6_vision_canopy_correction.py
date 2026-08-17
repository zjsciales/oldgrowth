"""vision-corrected canopy + house/lot summary fields

Revision ID: e1f2a3b4c5d6
Revises: d5e6f7a8b9c0
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TAG_TABLE = sa.table('tags', sa.column('code', sa.String), sa.column('mapped_features', sa.JSON))


def upgrade() -> None:
    op.add_column('listing_features', sa.Column('effective_canopy_pct', sa.Float(), nullable=True))
    op.add_column('listing_features', sa.Column('vision_canopy_pct_estimate', sa.Float(), nullable=True))
    op.add_column('listing_features', sa.Column('canopy_condition', sa.String(), nullable=True))
    op.add_column('listing_features', sa.Column('canopy_condition_confidence', sa.Float(), nullable=True))
    op.add_column(
        'listing_features',
        sa.Column('canopy_pct_overridden_by_vision', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('listing_features', sa.Column('house_lot_summary', sa.String(), nullable=True))

    # canopy/model.py now trains on effective_canopy_pct, not the raw
    # parcel_canopy_pct -- seeded tags mapped to the old column name
    # (migrations/versions/10ce20f0c80a_add_rating_schema.py) would
    # otherwise silently stop matching any column in the model's raw
    # feature rows, disabling hinge-threshold learning for these tags.
    for code in ('lot_too_open', 'mature_canopy'):
        op.execute(TAG_TABLE.update().where(TAG_TABLE.c.code == code).values(mapped_features=['effective_canopy_pct']))


def downgrade() -> None:
    for code in ('lot_too_open', 'mature_canopy'):
        op.execute(TAG_TABLE.update().where(TAG_TABLE.c.code == code).values(mapped_features=['parcel_canopy_pct']))

    op.drop_column('listing_features', 'house_lot_summary')
    op.drop_column('listing_features', 'canopy_pct_overridden_by_vision')
    op.drop_column('listing_features', 'canopy_condition_confidence')
    op.drop_column('listing_features', 'canopy_condition')
    op.drop_column('listing_features', 'vision_canopy_pct_estimate')
    op.drop_column('listing_features', 'effective_canopy_pct')
