#!/bin/bash
set -e

# ============================================
#  🔀 RouterAI — Container Entrypoint
#  Ensures config files exist before starting
# ============================================

mkdir -p /app/data/cache

# Create config files in DATA_DIR if they don't exist.
# Migration from legacy paths is handled by server.py _migrate_legacy_file()
[ ! -f /app/data/api_keys.json ] && echo '{}' > /app/data/api_keys.json
[ ! -f /app/data/proxy_config.json ] && echo '{}' > /app/data/proxy_config.json

echo "✅ RouterAI initialized — data at /app/data"

# Execute the main command
exec "$@"
