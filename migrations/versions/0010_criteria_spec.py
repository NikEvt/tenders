"""Спецификация фильтра — только в JSONB

`saved_filters` держал две денормализованные копии полей спецификации:
`llm_criteria` и `semantic_query`. В новом формате критерия таких полей нет —
есть термины, роли и правила по контексту, и вынести их в отдельные колонки
невозможно, да и незачем: `spec` и был источником правды, а копии существовали
ради удобства старого движка.

Revision ID: 0010_criteria_spec
Revises: 0009_drop_old_filters
Create Date: 2026-08-13 15:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0010_criteria_spec'
down_revision: str | None = '0009_drop_old_filters'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column('saved_filters', 'llm_criteria')
    op.drop_column('saved_filters', 'semantic_query')


def downgrade() -> None:
    # Колонки вернутся пустыми: данных в них к этому моменту уже не было —
    # фильтры прежнего формата удалены миграцией 0009.
    op.add_column('saved_filters', sa.Column('semantic_query', sa.Text(), nullable=True))
    op.add_column('saved_filters', sa.Column('llm_criteria', sa.Text(), nullable=True))
