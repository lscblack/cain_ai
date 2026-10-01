#!/usr/bin/env bash
# KAI dev setup helper. Run from repo root. Idempotent-ish.
set -euo pipefail

echo "[kai] bringing up Redis via docker compose..."
docker compose up -d redis

echo "[kai] ensuring 'kai' database exists..."
PGPASSWORD="${DB_PASSWORD:-YourStrongPassword}" psql -h "${DB_HOST:-127.0.0.1}" \
  -p "${DB_PORT:-5432}" -U "${DB_USER:-postgres}" -tc \
  "SELECT 1 FROM pg_database WHERE datname='kai'" | grep -q 1 \
  || PGPASSWORD="${DB_PASSWORD:-YourStrongPassword}" createdb -h "${DB_HOST:-127.0.0.1}" \
       -p "${DB_PORT:-5432}" -U "${DB_USER:-postgres}" kai

echo "[kai] applying migrations..."
( cd backend && alembic upgrade head )

echo "[kai] done. Start backend:  cd backend && uvicorn app.main:app --reload --app-dir ."
echo "[kai]       Start frontend: cd frontend && pnpm install && pnpm dev"
