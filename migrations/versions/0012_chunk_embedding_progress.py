"""Частичный индекс под счётчик векторизованных фрагментов

Вкладка «Данные» показывает, какая часть корпуса готова к семантическому
поиску, и опрашивает это раз в пятнадцать секунд. Замер на живом корпусе
(2.0 млн фрагментов, из них векторизовано 20.5 тыс.):

    count(*) where embedding is not null   →  2314 мс, parallel seq scan
    то же с этим индексом                  →     см. baseline.md

Два гигабайта векторов пролистывались целиком ради числа, которое лежит в
двадцати тысячах строк. Индекс частичный именно поэтому: полный индекс по
колонке был бы размером с таблицу и решал бы не ту задачу.

`CONCURRENTLY` не используется: оно требует работы вне транзакции, а alembic
ведёт миграции транзакционно. На таблице такого размера построение занимает
секунды и делается в окно обновления.

Revision ID: 0012_chunk_embedding_progress
Revises: 0011_job_phase
Create Date: 2026-08-15 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0012_chunk_embedding_progress'
down_revision: str | None = '0011_job_phase'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        'document_chunks_embedded_idx',
        'document_chunks',
        ['id'],
        postgresql_where="embedding IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index('document_chunks_embedded_idx', table_name='document_chunks')
