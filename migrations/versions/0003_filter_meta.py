"""Метаданные сохранённых фильтров: сводка, уведомления, время прогона

Revision ID: 0003_filter_meta
Revises: 0002_platform
Create Date: 2026-08-09 10:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003_filter_meta'
down_revision: str | None = '0002_platform'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Тумблеры страницы фильтров. По умолчанию фильтр попадает в сводку, но не
    # шлёт уведомлений: сводку читают раз в день, а уведомление перебивает работу.
    op.add_column(
        'saved_filters',
        sa.Column('in_digest', sa.Boolean(), server_default='true', nullable=False),
    )
    op.add_column(
        'saved_filters',
        sa.Column('notify', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'saved_filters',
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    )
    # Спарклайн «сколько совпало по дням» группирует вердикты по дате.
    op.create_index(
        'llm_verdicts_filter_created_idx', 'llm_verdicts', ['filter_id', 'created_at']
    )


def downgrade() -> None:
    op.drop_index('llm_verdicts_filter_created_idx', table_name='llm_verdicts')
    op.drop_column('saved_filters', 'last_run_at')
    op.drop_column('saved_filters', 'notify')
    op.drop_column('saved_filters', 'in_digest')
