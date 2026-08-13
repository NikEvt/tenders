"""Эксплуатационные данные: запуски краулера, состояние приложения, ручные веса

Revision ID: 0005_ops
Revises: 0004_chunk_offsets
Create Date: 2026-08-09 14:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005_ops'
down_revision: str | None = '0004_chunk_offsets'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Код и сырой ответ ЕИС: сейчас в логе остаётся только текст ошибки, а по
    # нему не отличить «организация заблокирована» от «сеть не ответила».
    op.add_column('crawler_runs', sa.Column('error_code', sa.Integer(), nullable=True))
    op.add_column(
        'crawler_runs',
        sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Единственная таблица, в которую пишет шлюз: у неё нет других писателей.
    # Здесь живёт подтверждение ротации токена и прочие отметки интерфейса.
    op.create_table(
        'app_settings',
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('key'),
    )

    # Ручные веса профиля. Отдельной колонкой, а не поверх вычисленных: иначе
    # ближайшая пересборка профиля молча затрёт правку пользователя.
    op.add_column(
        'recommendation_profiles',
        sa.Column('manual_weights', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Событийный след закупки ищет по tender_id внутри payload.
    op.create_index(
        'outbox_payload_tender_idx',
        'outbox',
        [sa.text("((payload ->> 'tender_id'))")],
    )


def downgrade() -> None:
    op.drop_index('outbox_payload_tender_idx', table_name='outbox')
    op.drop_column('recommendation_profiles', 'manual_weights')
    op.drop_table('app_settings')
    op.drop_column('crawler_runs', 'raw')
    op.drop_column('crawler_runs', 'error_code')
