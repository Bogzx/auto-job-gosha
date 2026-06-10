#!/usr/bin/env bash
# Run on the NEW VPS: debug postgres auth, then migrate SQLite -> Postgres.
set -e
cd ~/gosha
set -a; source .env; set +a
echo "env password length: ${#POSTGRES_PASSWORD}"
echo "container password length:"
docker exec gosha-postgres sh -c 'echo ${#POSTGRES_PASSWORD}'
echo "--- direct psql test ---"
docker exec gosha-postgres psql -U gosha -d gosha -c "select count(*) as users from users;" | tail -3
echo "--- migration ---"
docker compose -f docker-compose.prod.yml run --rm -e PYTHONPATH=/app bot \
  python scripts/migrate_sqlite_to_postgres.py \
  sqlite+aiosqlite:///data/jobs.db \
  "postgresql+asyncpg://gosha:${POSTGRES_PASSWORD}@postgres:5432/gosha" 2>&1 | tail -12
