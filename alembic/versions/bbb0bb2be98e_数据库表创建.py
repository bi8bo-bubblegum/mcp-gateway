"""数据库表创建

Revision ID: bbb0bb2be98e
Revises: 
Create Date: 2026-09-24 14:55:40.093672

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bbb0bb2be98e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('token_id', sa.Integer(), nullable=True),
    sa.Column('token_name', sa.String(length=128), nullable=True),
    sa.Column('service_slug', sa.String(length=64), nullable=True),
    sa.Column('tool_name', sa.String(length=256), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('denial_reason', sa.String(length=64), nullable=True),
    sa.Column('error_type', sa.String(length=128), nullable=True),
    sa.Column('argument_keys', sa.JSON(), nullable=False),
    sa.Column('requested_argument_hashes', sa.JSON(), nullable=False),
    sa.Column('effective_argument_hashes', sa.JSON(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_events_started_at', 'audit_events', ['started_at'], unique=False)
    op.create_index('ix_audit_events_token_id', 'audit_events', ['token_id'], unique=False)
    op.create_index('ix_audit_events_tool_name', 'audit_events', ['tool_name'], unique=False)
    op.create_table('gateway_revision',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('services',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('url', sa.String(length=512), nullable=False),
    sa.Column('auth_ciphertext', sa.Text(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('health', sa.String(length=16), nullable=False),
    sa.Column('consecutive_failures', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_refreshed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('token_prefix', sa.String(length=16), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('allow_high_risk', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_table('token_services',
    sa.Column('token_id', sa.Integer(), nullable=False),
    sa.Column('service_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['token_id'], ['tokens.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_id', 'service_id')
    )
    op.create_table('tools',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('service_id', sa.Integer(), nullable=False),
    sa.Column('upstream_name', sa.String(length=128), nullable=False),
    sa.Column('effective_name', sa.String(length=256), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('input_schema', sa.JSON(), nullable=False),
    sa.Column('schema_hash', sa.String(length=64), nullable=False),
    sa.Column('risk', sa.String(length=8), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('available', sa.Boolean(), nullable=False),
    sa.Column('discovered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('effective_name'),
    sa.UniqueConstraint('service_id', 'upstream_name', name='uq_tools_service_upstream')
    )
    op.create_table('parameter_injections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_id', sa.Integer(), nullable=False),
    sa.Column('tool_id', sa.Integer(), nullable=False),
    sa.Column('argument', sa.String(length=128), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['token_id'], ['tokens.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_id', 'tool_id', 'argument')
    )
    op.create_table('token_tools',
    sa.Column('token_id', sa.Integer(), nullable=False),
    sa.Column('tool_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['token_id'], ['tokens.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_id', 'tool_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('token_tools')
    op.drop_table('parameter_injections')
    op.drop_table('tools')
    op.drop_table('token_services')
    op.drop_table('tokens')
    op.drop_table('services')
    op.drop_table('gateway_revision')
    op.drop_index('ix_audit_events_tool_name', table_name='audit_events')
    op.drop_index('ix_audit_events_token_id', table_name='audit_events')
    op.drop_index('ix_audit_events_started_at', table_name='audit_events')
    op.drop_table('audit_events')
