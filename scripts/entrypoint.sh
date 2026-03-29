#!/bin/bash
set -e

# ============================================
#  🔀 RouterAI — Container Entrypoint
#  Ensures config files exist before starting
# ============================================

mkdir -p /app/data/cache

# Create config files if they don't exist
[ ! -f /app/api_keys.json ] && echo '{}' > /app/api_keys.json
[ ! -f /app/proxy_config.json ] && echo '{}' > /app/proxy_config.json

echo "✅ RouterAI initialized — data at /app/data"

# Execute the main command
exec "$@"
