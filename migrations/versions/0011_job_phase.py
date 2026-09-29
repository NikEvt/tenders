"""Фаза длительного задания

Долгая операция состоит из фаз с разной ценой единицы работы: прогон
исследования — это обход корпуса, а затем судья, и вторая фаза дороже первой
на порядок. Пока фазы не было, `processed`/`total` описывали только первую:
шкала доходила до конца обхода и стояла там минуты, пока работал судья. Это
хуже отсутствия шкалы — шкала, дошедшая до ста процентов, утверждает, что
операция закончена.

Колонка nullable: у заданий, начатых до миграции, фазы не было, и придумывать
её задним числом не за что.

Revision ID: 0011_job_phase
Revises: 0010_criteria_spec
Create Date: 2026-08-15 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0011_job_phase'
down_revision: str | None = '0010_criteria_spec'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('phase', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'phase')
