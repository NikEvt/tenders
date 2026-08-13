"""Базовая линия: схема, существовавшая в db/init.sql до перехода на Alembic.

Ревизия нужна, чтобы уже работающую базу (в ней ~1100 извещений) можно было
перевести под управление миграций без потери данных:

    alembic stamp 0001_baseline   # существующая база — просто помечается
    alembic upgrade head          # и дальше догоняет изменения

Для пустой базы `alembic upgrade head` отработает эту ревизию обычным способом.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "tenders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reg_num", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.Text(), server_default="RUB", nullable=True),
        sa.Column("publish_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("direct_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_publish_date", sa.Date(), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prev_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bidding_date", sa.Date(), nullable=True),
        sa.Column("summarizing_date", sa.Date(), nullable=True),
        sa.Column("contract_end_date", sa.Date(), nullable=True),
        sa.Column("customer_name", sa.Text(), nullable=True),
        sa.Column("customer_inn", sa.Text(), nullable=True),
        sa.Column("customer_region", sa.Text(), nullable=True),
        sa.Column("okpd2_code", sa.Text(), nullable=True),
        sa.Column("okpd2_name", sa.Text(), nullable=True),
        sa.Column("law_type", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("raw_xml", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reg_num"),
    )
    op.execute("CREATE INDEX tenders_publish_date_idx ON tenders (publish_date DESC)")
    op.create_index("tenders_okpd2_idx", "tenders", ["okpd2_code"])
    op.create_index("tenders_inn_idx", "tenders", ["customer_inn"])
    op.execute(
        "CREATE INDEX tenders_embedding_idx ON tenders "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "crawler_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched", sa.Integer(), server_default="0"),
        sa.Column("errors", sa.Integer(), server_default="0"),
        sa.Column("status", sa.Text(), server_default="running"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("crawler_runs")
    op.drop_table("tenders")
