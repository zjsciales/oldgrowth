"""email-sourced listings: source/photo/dedup fields, nullable lat/lon/zip, EmailIngestLog

Revision ID: c4a91f0d2b3e
Revises: b3d4f1a9c7e2
Create Date: 2026-08-16 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a91f0d2b3e'
down_revision: Union[str, None] = 'b3d4f1a9c7e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('listings', sa.Column('source', sa.String(), nullable=False, server_default='rentcast'))
    op.add_column('listings', sa.Column('source_listing_id', sa.String(), nullable=True))
    op.add_column('listings', sa.Column('normalized_address', sa.String(), nullable=True))
    op.add_column('listings', sa.Column('photo_url', sa.String(), nullable=True))
    op.add_column('listings', sa.Column('photo_urls', sa.JSON(), nullable=True))
    op.create_index(op.f('ix_listings_source_listing_id'), 'listings', ['source_listing_id'], unique=False)
    op.create_index(op.f('ix_listings_normalized_address'), 'listings', ['normalized_address'], unique=False)

    op.alter_column('listings', 'latitude', existing_type=sa.Float(), nullable=True)
    op.alter_column('listings', 'longitude', existing_type=sa.Float(), nullable=True)
    op.alter_column('listings', 'zip_code', existing_type=sa.String(), nullable=True)

    op.create_table(
        'email_ingest_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('message_id', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('listings_found', sa.Integer(), nullable=False),
        sa.Column('listings_parsed_ok', sa.Integer(), nullable=False),
        sa.Column('parse_errors', sa.JSON(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_email_ingest_log_message_id'), 'email_ingest_log', ['message_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_email_ingest_log_message_id'), table_name='email_ingest_log')
    op.drop_table('email_ingest_log')

    op.alter_column('listings', 'zip_code', existing_type=sa.String(), nullable=False)
    op.alter_column('listings', 'longitude', existing_type=sa.Float(), nullable=False)
    op.alter_column('listings', 'latitude', existing_type=sa.Float(), nullable=False)

    op.drop_index(op.f('ix_listings_normalized_address'), table_name='listings')
    op.drop_index(op.f('ix_listings_source_listing_id'), table_name='listings')
    op.drop_column('listings', 'photo_urls')
    op.drop_column('listings', 'photo_url')
    op.drop_column('listings', 'normalized_address')
    op.drop_column('listings', 'source_listing_id')
    op.drop_column('listings', 'source')
