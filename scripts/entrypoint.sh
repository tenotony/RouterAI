#!/bin/bash
set -e

# ============================================
#  🔀 RouterAI — Container Entrypoint
#  Ensures config files exist before starting
# ============================================

mkdir -p /app/config /app/data/cache

# Create config files if they don't exist (preserves volume data)
[ ! -f /app/config/api_keys.json ] && echo '{}' > /app/config/api_keys.json
[ ! -f /app/config/proxy_config.json ] && echo '{}' > /app/config/proxy_config.json

# Symlink for backward compatibility (code reads from /app/*.json)
ln -sf /app/config/api_keys.json /app/api_keys.json 2>/dev/null || true
ln -sf /app/config/proxy_config.json /app/proxy_config.json 2>/dev/null || true

echo "✅ RouterAI initialized — config at /app/config, data at /app/data"

# Execute the main command
exec "$@"
