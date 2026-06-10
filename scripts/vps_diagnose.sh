echo "=== bot status ==="
docker ps --format '{{.Names}} {{.Status}}' | grep gosha-bot
echo "=== scheduler / scrape log lines ==="
docker logs gosha-bot 2>&1 | grep -E "next run|Scheduler started|scrape|Scrape" | tail -10
echo "=== recent errors ==="
docker logs gosha-bot 2>&1 | grep -iE "error|exception|traceback" | tail -6
echo "=== last job.discovered event ==="
docker exec gosha-postgres psql -U gosha -d gosha -t -A -c "select coalesce(max(timestamp)::text,'NEVER') from events where event_type='job.discovered';"
echo "=== newest job last_seen_at ==="
docker exec gosha-postgres psql -U gosha -d gosha -t -A -c "select max(last_seen_at) from jobs;"
echo "=== deliveries since cutover ==="
docker exec gosha-postgres psql -U gosha -d gosha -t -A -c "select count(*) from user_jobs where delivered_at > '2026-06-10 10:00';"
echo "=== bot container started at ==="
docker inspect gosha-bot --format '{{.State.StartedAt}}'
