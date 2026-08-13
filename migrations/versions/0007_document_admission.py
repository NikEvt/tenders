"""Приоритет вложения и причина отказа

Политика допуска решает судьбу вложения до скачивания. Чтобы это было видно в
воронке, рядом с документом хранится и то, каким по счёту его собирались
разбирать, и то, почему не стали.

Индекс по приоритету нужен обзорным проходам: «взять только ТЗ и обоснования по
всем закупкам региона» — это `WHERE priority <= 1`, и без индекса он выливается
в полный проход по таблице вложений.

Revision ID: 0007_document_admission
Revises: 0006_text_to_object_storage
Create Date: 2026-08-13 13:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0007_document_admission'
down_revision: str | None = '0006_text_to_object_storage'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL у вложений, заведённых до появления политики: приоритет им будет
    # проставлен при первой же обработке закупки.
    op.add_column('tender_documents', sa.Column('priority', sa.SmallInteger(), nullable=True))
    op.create_index(
        'ix_tender_documents_priority', 'tender_documents', ['priority'], unique=False
    )

    op.add_column(
        'tender_documents', sa.Column('skip_reason', sa.String(length=24), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('tender_documents', 'skip_reason')
    op.drop_index('ix_tender_documents_priority', table_name='tender_documents')
    op.drop_column('tender_documents', 'priority')
