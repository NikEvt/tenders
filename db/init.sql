-- Выполняется один раз при создании тома Postgres.
-- Только расширения: вся схема живёт в Alembic (migrations/), иначе DDL
-- расползается по двум источникам и расходится с моделями.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
