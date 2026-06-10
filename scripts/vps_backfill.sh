cd ~/gosha
docker compose -f docker-compose.prod.yml run --rm -e PYTHONPATH=/app bot python - <<'EOF'
import asyncio, os
from gosha import database
from gosha.embeddings import embed_new_jobs

async def main():
    await database.init_db(os.environ["DATABASE_URL"])
    total = 0
    while True:
        n = await embed_new_jobs(limit=200)
        total += n
        print(f"embedded {n} (total {total})", flush=True)
        if n == 0:
            break

asyncio.run(main())
EOF
echo "--- embedding coverage ---"
docker exec gosha-postgres psql -U gosha -d gosha -c "select count(*) filter (where embedding is not null) as with_vec, count(*) as total from jobs;"
