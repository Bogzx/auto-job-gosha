#!/usr/bin/env bash
# Run on the OLD VPS: stop the bot and checkpoint the SQLite WAL for copying.
set -e
cd ~/Gosha/autojobGOSHA
docker compose stop | tail -2 || docker stop job-bot gosha-admin
python3 - <<'EOF'
import sqlite3
conn = sqlite3.connect("data/jobs.db")
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
conn.close()
print("checkpointed")
EOF
ls -la data/jobs.db*
