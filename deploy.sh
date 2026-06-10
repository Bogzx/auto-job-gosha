#!/usr/bin/env bash
# Deploy/update the GOSHA platform on the VPS.
#   ./deploy.sh          # pull latest + rebuild + restart
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERROR: .env missing — cp .env.example .env and fill in secrets first." >&2
  exit 1
fi

git pull --ff-only
docker compose -f docker-compose.prod.yml up -d --build
docker image prune -f

echo
docker compose -f docker-compose.prod.yml ps
echo "Deployed. Logs: docker compose -f docker-compose.prod.yml logs -f --tail=50"
