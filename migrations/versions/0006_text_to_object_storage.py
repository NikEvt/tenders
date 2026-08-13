"""Извлечённый текст переезжает в объектное хранилище

Добавляет ключ объекта и хеш текста, снимает NOT NULL с `content`.

`content` здесь **не удаляется**. Копирование данных и снос их источника в одной
миграции не оставляют возможности откатиться: если перенос окажется неполным,
возвращать будет уже нечего. Поэтому порядок такой — эта миграция расширяет
схему, `scripts/migrate_texts_to_storage.py` переносит текст пачками, и только
после сверки `content` убирается миграцией 0007.

Revision ID: 0006_text_to_object_storage
Revises: 0005_ops
Create Date: 2026-08-13 12:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006_text_to_object_storage'
down_revision: str | None = '0005_ops'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ключ объекта с текстом. NULL означает «ещё не перенесён» — в этом случае
    # читатели берут текст из `content`.
    op.add_column('document_texts', sa.Column('text_key', sa.Text(), nullable=True))

    # sha256 текста. Ключ объекта строится из него же, поэтому одинаковый текст
    # физически хранится один раз; по этому полю видно, сколько документов
    # ссылаются на один объект.
    op.add_column(
        'document_texts', sa.Column('text_sha256', sa.String(length=64), nullable=True)
    )
    op.create_index(
        'document_texts_sha_idx', 'document_texts', ['text_sha256'], unique=False
    )

    # Новые строки текст в базу больше не кладут.
    op.alter_column('document_texts', 'content', existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    # Возврат возможен, только пока `content` цел: строки, записанные уже в
    # хранилище, останутся без текста в базе, и NOT NULL их не пропустит.
    op.execute("UPDATE document_texts SET content = '' WHERE content IS NULL")
    op.alter_column('document_texts', 'content', existing_type=sa.Text(), nullable=False)
    op.drop_index('document_texts_sha_idx', table_name='document_texts')
    op.drop_column('document_texts', 'text_sha256')
    op.drop_column('document_texts', 'text_key')
