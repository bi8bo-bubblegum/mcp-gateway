"""AI 网关数据表

Revision ID: f0a1b2c3d4e5
Revises: bbb0bb2be98e
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'bbb0bb2be98e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ai_providers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('base_url', sa.String(length=512), nullable=False),
    # 上游密钥加密存储，绝不落明文
    sa.Column('api_key_ciphertext', sa.Text(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('health', sa.String(length=16), nullable=False),
    sa.Column('consecutive_failures', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.String(length=2000), nullable=True),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('guardrail_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('pattern', sa.String(length=512), nullable=False),
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('action', sa.String(length=16), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ai_models',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider_id', sa.Integer(), nullable=False),
    sa.Column('provider_model_name', sa.String(length=128), nullable=False),
    # 对外暴露名，客户端 model 字段填这个
    sa.Column('alias', sa.String(length=128), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    # 每千 token 单价，仅用于成本展示
    sa.Column('input_price', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('output_price', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['provider_id'], ['ai_providers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('alias'),
    sa.UniqueConstraint('provider_id', 'provider_model_name', name='uq_ai_models_provider_upstream')
    )
    op.create_table('ai_api_keys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    # 只存 HMAC 哈希，明文只在创建时返回一次
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('owner', sa.String(length=128), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    # 周期 token 配额，null = 不限
    sa.Column('period_token_limit', sa.BigInteger(), nullable=True),
    sa.Column('period', sa.String(length=16), nullable=False),
    sa.Column('rate_limit_rpm', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_hash')
    )
    op.create_table('ai_key_models',
    sa.Column('key_id', sa.Integer(), nullable=False),
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['key_id'], ['ai_api_keys.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['model_id'], ['ai_models.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('key_id', 'model_id')
    )
    op.create_table('ai_usage_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=False),
    sa.Column('key_id', sa.Integer(), nullable=True),
    sa.Column('key_name', sa.String(length=128), nullable=True),
    sa.Column('model_id', sa.Integer(), nullable=True),
    sa.Column('model_alias', sa.String(length=128), nullable=True),
    sa.Column('provider_slug', sa.String(length=32), nullable=True),
    sa.Column('endpoint', sa.String(length=64), nullable=False),
    sa.Column('stream', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('denial_reason', sa.String(length=64), nullable=True),
    sa.Column('error_type', sa.String(length=64), nullable=True),
    sa.Column('upstream_status_code', sa.Integer(), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('total_tokens', sa.Integer(), nullable=True),
    sa.Column('usage_estimated', sa.Boolean(), nullable=False),
    sa.Column('guardrail_hits', sa.JSON(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('first_token_ms', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ai_usage_events_started_at', 'ai_usage_events', ['started_at'], unique=False)
    op.create_table('ai_usage_daily',
    sa.Column('key_id', sa.Integer(), nullable=False),
    # 复合主键 (key_id, day)，同时也是配额热路径的唯一索引
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('requests', sa.BigInteger(), nullable=False),
    sa.Column('prompt_tokens', sa.BigInteger(), nullable=False),
    sa.Column('completion_tokens', sa.BigInteger(), nullable=False),
    sa.Column('total_tokens', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['key_id'], ['ai_api_keys.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('key_id', 'day')
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 按依赖倒序 drop：先删引用方的表
    op.drop_table('ai_usage_daily')
    op.drop_table('ai_key_models')
    op.drop_index('ix_ai_usage_events_started_at', table_name='ai_usage_events')
    op.drop_table('ai_usage_events')
    op.drop_table('ai_api_keys')
    op.drop_table('ai_models')
    op.drop_table('guardrail_rules')
    op.drop_table('ai_providers')
