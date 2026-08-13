"""Границы чанков внутри текста документа

Revision ID: 0004_chunk_offsets
Revises: 0003_filter_meta
Create Date: 2026-08-09 12:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004_chunk_offsets'
down_revision: str | None = '0003_filter_meta'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: у чанков, нарезанных до этой ревизии, смещений нет, и заполнить
    # их можно только выравниванием (см. services.docs_worker.backfill_offsets).
    # Строка, для которой выравнивание не сошлось, остаётся с NULL — клиент
    # честно скажет «источник не указан» вместо ложной подсветки.
    op.add_column('document_chunks', sa.Column('char_start', sa.Integer(), nullable=True))
    op.add_column('document_chunks', sa.Column('char_end', sa.Integer(), nullable=True))
    # Порядок внутри документа: и для выдачи границ, и для поиска вперёд при
    # выравнивании истории.
    op.create_index(
        'document_chunks_document_order_idx', 'document_chunks', ['document_id', 'chunk_index']
    )


def downgrade() -> None:
    op.drop_index('document_chunks_document_order_idx', table_name='document_chunks')
    op.drop_column('document_chunks', 'char_end')
    op.drop_column('document_chunks', 'char_start')
