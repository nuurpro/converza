#!/usr/bin/env bash
# One-command local spin-up for Converza
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "Created .env from .env.example — add your Anthropic key, then re-run."
    echo "  Set ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) in .env"
    exit 1
  fi
  echo "Missing .env — copy .env.example and set ANTHROPIC_API_KEY"
  exit 1
fi

# Load .env for the key check (simple KEY=VALUE lines)
set -a
# shellcheck disable=SC1091
source .env
set +a

KEY="${ANTHROPIC_API_KEY:-${ANTHROPIC_AUTH_TOKEN:-}}"
if [[ -z "${KEY}" ]]; then
  echo "Set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN in .env before starting."
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "Starting Converza with Docker Compose..."
  exec docker compose up --build
fi

echo "Docker not found — falling back to Node..."
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
# shellcheck disable=SC1091
[[ -s "$NVM_DIR/nvm.sh" ]] && . "$NVM_DIR/nvm.sh"

if [[ ! -d node_modules ]]; then
  npm install
fi

exec npm start
