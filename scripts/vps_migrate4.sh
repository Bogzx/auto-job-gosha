cd ~/gosha
PGPASS=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2)
echo "--- wiping partial migration ---"
docker exec gosha-postgres psql -U gosha -d gosha -c "TRUNCATE users, jobs, subscriptions, user_jobs, applications, cover_letters, events, outbox RESTART IDENTITY CASCADE;"
echo "--- migrating ---"
docker compose -f docker-compose.prod.yml run --rm -e PYTHONPATH=/app \
  -v /tmp/mig.py:/app/scripts/migrate_sqlite_to_postgres.py bot \
  python scripts/migrate_sqlite_to_postgres.py \
  sqlite+aiosqlite:///data/jobs.db \
  "postgresql+asyncpg://gosha:${PGPASS}@postgres:5432/gosha" 2>&1 | tail -14
echo "--- post-migration counts ---"
docker exec gosha-postgres psql -U gosha -d gosha -c "select (select count(*) from users) as users, (select count(*) from subscriptions) as subs, (select count(*) from jobs) as jobs, (select count(*) from user_jobs) as deliveries, (select count(*) from applications) as apps, (select count(*) from cover_letters) as letters;"
