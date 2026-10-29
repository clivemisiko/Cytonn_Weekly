#!/usr/bin/env bash
# Pull and restart api and web from ghcr.io. Usage: ./deploy.sh [tag]   (default latest; sha-<commit> to roll back)
set -euo pipefail

# Works from a flat copy (deploy.sh beside docker-compose.yml) or a clone (deploy/deploy.sh).
cd "$(dirname "$0")"
[ -f docker-compose.yml ] || cd ..

if [ -f docker-compose.server.yml ]; then server=docker-compose.server.yml; else server=deploy/docker-compose.server.yml; fi

if [ -d .git ]; then
  git pull --ff-only
else
  echo "Not a git clone: skipping git pull, compose files and Caddyfile are as copied."
fi

export IMAGE_TAG="${1:-latest}"
compose=(docker compose -f docker-compose.yml -f "$server")

"${compose[@]}" pull api web
# Only api and web: the proxy is not recreated, so its certificate and login stay as they are.
"${compose[@]}" up -d api web
docker image prune -f
"${compose[@]}" ps
