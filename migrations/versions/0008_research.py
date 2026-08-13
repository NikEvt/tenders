"""Исследования: прогоны, находки, вердикты

Три таблицы движка отбора.

`research_verdicts` намеренно не ссылается на прогон: решение принадлежит паре
«закупка + версия критериев», а не конкретному запуску. Поэтому повторный
прогон с теми же критериями не тратит токенов, а правка шаблонов обесценивает
кэш сама собой — через версию в ключе.

Воронка живёт в `research_runs` рядом с прогоном: без знаменателей её числа не
значат ничего. «Находок нет» — вывод только тогда, когда известно, сколько
документов при этом прочитано.

Revision ID: 0008_research
Revises: 0007_document_admission
Create Date: 2026-08-13 14:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0008_research'
down_revision: str | None = '0007_document_admission'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'research_runs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('criteria_version', sa.String(length=32), nullable=False),
        sa.Column('criteria', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('regions', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('date_from', sa.Date(), nullable=True),
        sa.Column('date_to', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='running', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('tenders_total', sa.Integer(), server_default='0', nullable=False),
        sa.Column('tenders_candidate', sa.Integer(), server_default='0', nullable=False),
        sa.Column('documents_scanned', sa.Integer(), server_default='0', nullable=False),
        sa.Column('documents_pending', sa.Integer(), server_default='0', nullable=False),
        sa.Column('hits_found', sa.Integer(), server_default='0', nullable=False),
        sa.Column('tenders_confirmed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('tenders_rejected', sa.Integer(), server_default='0', nullable=False),
        sa.Column('tenders_disputed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_research_runs_criteria_version'), 'research_runs', ['criteria_version']
    )

    op.create_table(
        'research_hits',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.BigInteger(), nullable=False),
        sa.Column('tender_id', sa.BigInteger(), nullable=False),
        sa.Column('document_id', sa.BigInteger(), nullable=True),
        sa.Column('term', sa.Text(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('quote', sa.Text(), nullable=False),
        sa.Column('match_start', sa.Integer(), server_default='0', nullable=False),
        sa.Column('match_end', sa.Integer(), server_default='0', nullable=False),
        sa.Column('file_name', sa.Text(), nullable=True),
        sa.Column('page', sa.Integer(), nullable=True),
        sa.Column('source_offset', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['research_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tender_id'], ['tenders.id'], ondelete='CASCADE'),
        # Документ может исчезнуть при переразборе, а цитата остаётся
        # проверяемой сама по себе — поэтому SET NULL, а не CASCADE.
        sa.ForeignKeyConstraint(['document_id'], ['tender_documents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_research_hits_run_id'), 'research_hits', ['run_id'])
    op.create_index(op.f('ix_research_hits_tender_id'), 'research_hits', ['tender_id'])
    op.create_index('research_hits_run_tender_idx', 'research_hits', ['run_id', 'tender_id'])

    op.create_table(
        'research_verdicts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tender_id', sa.BigInteger(), nullable=False),
        sa.Column('criteria_version', sa.String(length=32), nullable=False),
        sa.Column('prompt_version', sa.String(length=32), nullable=False),
        sa.Column('confidence', sa.String(length=16), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('score', sa.Float(), server_default='0', nullable=False),
        sa.Column('decided_by', sa.String(length=16), server_default='rules', nullable=False),
        sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('model', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['tender_id'], ['tenders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # Ключ кэша: закупка + версия критериев + версия промпта.
        sa.UniqueConstraint(
            'tender_id', 'criteria_version', 'prompt_version', name='uq_research_verdict'
        ),
    )
    op.create_index(op.f('ix_research_verdicts_tender_id'), 'research_verdicts', ['tender_id'])
    op.create_index(op.f('ix_research_verdicts_confidence'), 'research_verdicts', ['confidence'])


def downgrade() -> None:
    op.drop_table('research_verdicts')
    op.drop_table('research_hits')
    op.drop_index(op.f('ix_research_runs_criteria_version'), table_name='research_runs')
    op.drop_table('research_runs')
