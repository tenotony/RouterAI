#!/bin/bash
# ============================================
#  🔀 RouterAI — One-Line Installer
#  curl -fsSL https://raw.githubusercontent.com/tenotony/RouterAI/main/scripts/install.sh | bash
# ============================================

set -e

REPO_URL="https://github.com/tenotony/RouterAI.git"
INSTALL_DIR="RouterAI"

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "  ${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "  ${CYAN}║${NC}  ${BOLD}🔀 RouterAI — ตัวติดตั้งอัตโนมัติ${NC}       ${CYAN}║${NC}"
echo -e "  ${CYAN}║${NC}  ${NC}รวม AI ฟรีสำหรับ OpenClaw${NC}              ${CYAN}║${NC}"
echo -e "  ${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Check Docker ────────────────────────────────────
echo -e "  ${BLUE}[1/4]${NC} ตรวจสอบ Docker..."

if command -v docker &> /dev/null && docker compose version &> /dev/null 2>&1; then
    echo -e "  ${GREEN}✅ Docker:${NC} $(docker --version | head -1)"
    USE_DOCKER=true
else
    echo -e "  ${YELLOW}⚠️  ไม่พบ Docker — จะใช้ Python venv แทน${NC}"
    USE_DOCKER=false
fi
echo ""

# ── Clone / Update ──────────────────────────────────
echo -e "  ${BLUE}[2/4]${NC} ดาวน์โหลด RouterAI..."

if [ -d "$INSTALL_DIR" ]; then
    echo -e "  ${YELLOW}⚠️  พบโฟลเดอร์ $INSTALL_DIR — อัพเดต...${NC}"
    cd "$INSTALL_DIR"
    # Backup user config
    BACKUP_DIR="/tmp/routerai-backup-$(date +%s)"
    mkdir -p "$BACKUP_DIR"
    for f in api_keys.json proxy_config.json .env; do
        [ -f "$f" ] && cp "$f" "$BACKUP_DIR/"
    done
    [ -d "data" ] && cp -r "data" "$BACKUP_DIR/" 2>/dev/null || true

    git checkout -- . 2>/dev/null || true
    git clean -fd 2>/dev/null || true
    git fetch origin main 2>&1
    git reset --hard origin/main 2>&1

    # Restore
    for f in api_keys.json proxy_config.json .env; do
        [ -f "$BACKUP_DIR/$f" ] && cp "$BACKUP_DIR/$f" "$f"
    done
    [ -d "$BACKUP_DIR/data" ] && cp -r "$BACKUP_DIR/data" . 2>/dev/null || true
    rm -rf "$BACKUP_DIR"
else
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi
echo -e "  ${GREEN}✅ ดาวน์โหลดเสร็จ${NC}"
echo ""

# ── Setup ───────────────────────────────────────────
echo -e "  ${BLUE}[3/4]${NC} ตั้งค่า..."

mkdir -p data/cache
[ ! -f api_keys.json ] && echo '{}' > api_keys.json
[ ! -f proxy_config.json ] && echo '{}' > proxy_config.json
[ ! -f .env ] && cp .env.example .env 2>/dev/null || true

echo -e "  ${GREEN}✅ ตั้งค่าเรียบร้อย${NC}"
echo ""

# ── Start ───────────────────────────────────────────
echo -e "  ${BLUE}[4/4]${NC} เริ่มระบบ..."

if [ "$USE_DOCKER" = true ]; then
    docker compose down 2>/dev/null || true
    docker compose build --no-cache 2>&1 | tail -5
    docker compose up -d 2>&1

    sleep 3
    if docker compose ps | grep -q "Up"; then
        echo -e "  ${GREEN}✅ Docker containers รันแล้ว${NC}"
    else
        echo -e "  ${RED}❌ มีปัญหา — ดู log: docker compose logs${NC}"
    fi
else
    # Python venv
    PYTHON="python3"
    if ! command -v python3 &> /dev/null; then
        echo -e "  ${RED}❌ ไม่พบ Python3 — กรุณาติดตั้งก่อน${NC}"
        exit 1
    fi

    if [ ! -d "venv" ]; then
        $PYTHON -m venv venv
    fi
    source venv/bin/activate
    pip install --quiet --upgrade pip 2>/dev/null
    pip install --quiet -r requirements.txt 2>/dev/null

    echo -e "  ${GREEN}✅ ติดตั้ง packages เรียบร้อย${NC}"
    echo ""
    echo -e "  ${YELLOW}💡 รันด้วยคำสั่ง:${NC}"
    echo -e "     ${CYAN}cd $INSTALL_DIR${NC}"
    echo -e "     ${CYAN}source venv/bin/activate${NC}"
    echo -e "     ${CYAN}python src/server.py${NC}         # เปิดทั้ง Proxy + Dashboard port 8900"
fi
echo ""

# ── Done ────────────────────────────────────────────
echo -e "  ${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "  ${GREEN}${BOLD}║${NC}        ✅ ติดตั้งเสร็จเรียบร้อย! 🎉        ${GREEN}${BOLD}║${NC}"
echo -e "  ${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}📝 ขั้นตอนต่อไป:${NC}"
echo ""
echo -e "  ${CYAN}1.${NC} เปิด Dashboard: ${BLUE}http://localhost:8900${NC}"
echo -e "  ${CYAN}2.${NC} ไปหน้า \"จัดการ API Key\" ใส่ Key อย่างน้อย 1 ตัว"
echo -e "  ${CYAN}3.${NC} ไปหน้า \"เชื่อม OpenClaw\" สร้าง Config"
echo -e "  ${CYAN}4.${NC} วาง Config ใน ~/.openclaw/openclaw.json"
echo -e "  ${CYAN}5.${NC} รัน ${YELLOW}openclaw restart${NC}"
echo ""
echo -e "  ${BOLD}💡 แนะนำ:${NC} สมัคร Groq (ฟรี) ที่ ${BLUE}https://console.groq.com/keys${NC}"
echo ""
echo -e "  ${BOLD}🔄 อัพเดต:${NC} ${YELLOW}cd $INSTALL_DIR && bash scripts/update.sh${NC}"
echo ""
