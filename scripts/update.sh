#!/bin/bash
# ============================================
#  🔀 RouterAI — Update & Restart
#  ใช้: ./scripts/update.sh
# ============================================

set -e

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "  ${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "  ${CYAN}║${NC}  ${BOLD}🔀 RouterAI — อัพเดตอัตโนมัติ${NC}          ${CYAN}║${NC}"
echo -e "  ${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

cd "$INSTALL_DIR"

# ── 1. Backup ──────────────────────────────────────
echo -e "  ${BLUE}[1/5]${NC} สำรอง config ของคุณ..."
BACKUP_DIR="/tmp/routerai-backup-$(date +%s)"
mkdir -p "$BACKUP_DIR"
for f in api_keys.json proxy_config.json .env; do
    [ -f "$f" ] && cp "$f" "$BACKUP_DIR/"
done
[ -d "data" ] && cp -r "data" "$BACKUP_DIR/" 2>/dev/null || true
echo -e "  ${GREEN}✅ สำรองเรียบร้อย${NC}"

# ── 2. Pull ────────────────────────────────────────
echo -e "  ${BLUE}[2/5]${NC} ดึงโค้ดล่าสุด..."
git checkout -- . 2>/dev/null || true
git clean -fd 2>/dev/null || true
git fetch origin main 2>&1
git reset --hard origin/main 2>&1
echo -e "  ${GREEN}✅ ดึงโค้ดเรียบร้อย${NC}"

# ── 3. Restore ─────────────────────────────────────
echo -e "  ${BLUE}[3/5]${NC} กู้คืน config..."
for f in api_keys.json proxy_config.json .env; do
    [ -f "$BACKUP_DIR/$f" ] && cp "$BACKUP_DIR/$f" "$f"
done
[ -d "$BACKUP_DIR/data" ] && cp -r "$BACKUP_DIR/data" . 2>/dev/null || true
mkdir -p data/cache
[ ! -f api_keys.json ] && echo '{}' > api_keys.json
[ ! -f proxy_config.json ] && echo '{}' > proxy_config.json
rm -rf "$BACKUP_DIR"
echo -e "  ${GREEN}✅ กู้คืน config เรียบร้อย${NC}"

# ── 4. Rebuild ─────────────────────────────────────
echo -e "  ${BLUE}[4/5]${NC} Rebuild และ Restart..."
if command -v docker &> /dev/null && docker compose version &> /dev/null 2>&1; then
    docker compose down 2>/dev/null || true
    docker rmi routerai-proxy routerai-dashboard 2>/dev/null || true
    docker compose build --no-cache 2>&1 | tail -3
    docker compose up -d 2>&1
    echo -e "  ${GREEN}✅ Docker containers รันแล้ว${NC}"
else
    if [ -d "venv" ]; then
        source venv/bin/activate
        pip install --quiet -r requirements.txt 2>/dev/null
        echo -e "  ${GREEN}✅ packages อัพเดตเรียบร้อย${NC}"
    fi
fi

# ── 5. Verify ──────────────────────────────────────
echo -e "  ${BLUE}[5/5]${NC} ตรวจสอบ..."
sleep 3
if command -v docker &> /dev/null && docker compose version &> /dev/null 2>&1; then
    RUNNING=$(docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null || echo "")
    if echo "$RUNNING" | grep -q "Up"; then
        echo -e "  ${GREEN}✅ Containers รันปกติ${NC}"
    else
        echo -e "  ${RED}❌ มีปัญหา — docker compose logs${NC}"
    fi
fi

echo ""
echo -e "  ${GREEN}${BOLD}✅ อัพเดตเสร็จเรียบร้อย! 🎉${NC}"
echo -e "  Dashboard: ${BLUE}http://127.0.0.1:8899${NC}"
echo -e "  Proxy:     ${BLUE}http://127.0.0.1:8900/v1${NC}"
echo ""
