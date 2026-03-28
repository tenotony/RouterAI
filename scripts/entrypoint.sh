#!/bin/bash
set -e

# Create config directory
mkdir -p /app/config /app/data/cache

# Create config files if they don't exist
[ ! -f /app/config/api_keys.json ] && echo '{}' > /app/config/api_keys.json
[ ! -f /app/config/proxy_config.json ] && echo '{}' > /app/config/proxy_config.json

# Symlink for backward compatibility
ln -sf /app/config/api_keys.json /app/api_keys.json 2>/dev/null || true
ln -sf /app/config/proxy_config.json /app/proxy_config.json 2>/dev/null || true

echo "✅ Config initialized"

# Execute the main command
exec "$@"
