#!/bin/bash
# ============================================
#  🔀 RouterAI — Docker Installer
#  curl -fsSL https://raw.githubusercontent.com/tenotony/RouterAI/main/scripts/install-docker.sh | bash
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
echo -e "  ${CYAN}║${NC}  ${BOLD}🔀 RouterAI — Docker Installer${NC}           ${CYAN}║${NC}"
echo -e "  ${CYAN}║${NC}  รวม AI ฟรีสำหรับ OpenClaw 🇹🇭            ${CYAN}║${NC}"
echo -e "  ${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Check Docker ────────────────────────────────────
echo -e "  ${BLUE}[1/4]${NC} ตรวจสอบ Docker..."

if ! command -v docker &> /dev/null; then
    echo -e "  ${YELLOW}⚠️  ไม่พบ Docker — กำลังติดตั้ง...${NC}"
    if [ -f /etc/debian_version ]; then
        # Debian/Ubuntu
        sudo apt-get update -qq
        sudo apt-get install -y ca-certificates curl gnupg
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update -qq
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    elif [ -f /etc/redhat-release ]; then
        # RHEL/CentOS/Fedora
        sudo yum install -y yum-utils
        sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
        sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
        sudo systemctl start docker
        sudo systemctl enable docker
    else
        echo -e "  ${RED}❌ ไม่สามารถติดตั้ง Docker อัตโนมัติได้${NC}"
        echo -e "  ${YELLOW}กรุณาติดตั้ง Docker ด้วยตนเอง: https://docs.docker.com/get-docker/${NC}"
        exit 1
    fi
    echo -e "  ${GREEN}✅ ติดตั้ง Docker เรียบร้อย${NC}"
else
    echo -e "  ${GREEN}✅ Docker:${NC} $(docker --version | head -1)"
fi

# Check docker compose
if ! docker compose version &> /dev/null 2>&1; then
    echo -e "  ${YELLOW}⚠️  ไม่พบ docker compose plugin — ติดตั้ง...${NC}"
    if [ -f /etc/debian_version ]; then
        sudo apt-get install -y docker-compose-plugin
    elif [ -f /etc/redhat-release ]; then
        sudo yum install -y docker-compose-plugin
    fi
fi
echo -e "  ${GREEN}✅ Docker Compose พร้อมใช้${NC}"
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

    # Restore user config
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

# Create .env if not exists (Docker Compose needs it)
if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || touch .env
    echo -e "  ${YELLOW}📝 สร้างไฟล์ .env — ใส่ API Key ได้ใน Dashboard หรือแก้ไฟล์ .env${NC}"
fi

# Create empty config files
mkdir -p data/cache
[ ! -f api_keys.json ] && echo '{}' > api_keys.json
[ ! -f proxy_config.json ] && echo '{}' > proxy_config.json

# Fix Windows line endings if present
if command -v dos2unix &> /dev/null; then
    dos2unix scripts/*.sh 2>/dev/null || true
fi

# Make scripts executable
chmod +x scripts/*.sh 2>/dev/null || true

echo -e "  ${GREEN}✅ ตั้งค่าเรียบร้อย${NC}"
echo ""

# ── Start ───────────────────────────────────────────
echo -e "  ${BLUE}[4/4]${NC} เริ่มระบบ..."

# Clean up any old containers/volumes with conflicting state
docker compose down -v 2>/dev/null || true

# Build and start
docker compose build --no-cache 2>&1 | tail -3
docker compose up -d 2>&1

# Wait for health check
echo -e "  ${YELLOW}⏳ รอระบบเริ่มทำงาน...${NC}"
sleep 5

if docker compose ps 2>/dev/null | grep -q "Up\|healthy"; then
    echo -e "  ${GREEN}✅ Docker containers รันแล้ว!${NC}"
else
    echo -e "  ${YELLOW}⚠️  กำลังเริ่มทำงาน... ตรวจสอบด้วย: docker compose ps${NC}"
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
echo -e "  ${CYAN}2.${NC} ไปหน้า \"🔑 จัดการ API Key\" ใส่ Key อย่างน้อย 1 ตัว"
echo -e "  ${CYAN}3.${NC} ไปหน้า \"🤖 เชื่อม OpenClaw\" สร้าง Config"
echo -e "  ${CYAN}4.${NC} วาง Config ใน ~/.openclaw/openclaw.json"
echo -e "  ${CYAN}5.${NC} รัน ${YELLOW}openclaw restart${NC}"
echo ""
echo -e "  ${BOLD}💡 แนะนำ:${NC} สมัคร Groq (ฟรี) ที่ ${BLUE}https://console.groq.com/keys${NC}"
echo ""
echo -e "  ${BOLD}🔧 คำสั่งที่มีประโยชน์:${NC}"
echo -e "     ${CYAN}docker compose logs -f${NC}           ดู log"
echo -e "     ${CYAN}docker compose restart${NC}           รีสตาร์ท"
echo -e "     ${CYAN}docker compose down${NC}              หยุดระบบ"
echo -e "     ${CYAN}bash scripts/update.sh${NC}           อัพเดต"
echo ""
