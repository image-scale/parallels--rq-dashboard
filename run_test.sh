#!/bin/bash
set -eo pipefail

export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export CI=true

cd /workspace/rq-dashboard

redis-server --daemonize yes --loglevel warning

rm -rf .pytest_cache

pytest tests/ -v --tb=short -p no:cacheprovider --timeout=60 --no-header

