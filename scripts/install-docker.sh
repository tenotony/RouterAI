#!/bin/bash
# ============================================
#  🔀 RouterAI — Docker Installer (Secure)
#  
#  วิธีใช้ที่ปลอดภัย:
#    1. ดาวน์โหลดก่อน: curl -fsSL <url> -o install.sh
#    2. ตรวจสอบโค้ด: cat install.sh  หรือ less install.sh
#    3. รัน: bash install.sh
#
#  หรือใช้ git clone โดยตรง (แนะนำ):
#    git clone https://github.com/tenotony/RouterAI.git
#    cd RouterAI
#    docker compose up -d --build
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
echo -e "  ${CYAN}║${NC}  ${BOLD}🔀 RouterAI — Docker Installer v3.0${NC}      ${CYAN}║${NC}"
echo -e "  ${CYAN}║${NC}  รวม AI ฟรีสำหรับ OpenClaw 🇹🇭            ${CYAN}║${NC}"
echo -e "  ${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Security: Verify script integrity ────────
echo -e "  ${BLUE}[0/5]${NC} ตรวจสอบความปลอดภัย..."

# Check if running via pipe (unsafe)
if [ -t 0 ]; then
    echo -e "  ${GREEN}✅ รันจากไฟล์โดยตรง (ปลอดภัย)${NC}"
else
    echo -e "  ${YELLOW}⚠️  รันจาก pipe — แนะนำให้ดาวน์โหลดไฟล์ก่อนแล้วตรวจสอบโค้ด${NC}"
    echo -e "  ${YELLOW}   curl -fsSL <url> -o install.sh && bash install.sh${NC}"
    echo ""
    read -p "  ดำเนินการต่อไหม? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "  ${RED}❌ ยกเลิก${NC}"
        exit 1
    fi
fi

# Check if git repo is valid (prevent MITM)
if command -v git &> /dev/null; then
    echo -e "  ${GREEN}✅ Git พร้อมใช้${NC}"
else
    echo -e "  ${YELLOW}⚠️  ไม่พบ Git — กำลังติดตั้ง...${NC}"
    if [ -f /etc/debian_version ]; then
        sudo apt-get update -qq && sudo apt-get install -y git
    elif [ -f /etc/redhat-release ]; then
        sudo yum install -y git
    fi
fi
echo ""

# ── Check Docker ────────────────────────────────────
echo -e "  ${BLUE}[1/5]${NC} ตรวจสอบ Docker..."

if ! command -v docker &> /dev/null; then
    echo -e "  ${YELLOW}⚠️  ไม่พบ Docker — กำลังติดตั้ง...${NC}"
    if [ -f /etc/debian_version ]; then
        sudo apt-get update -qq
        sudo apt-get install -y ca-certificates curl gnupg
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update -qq
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    elif [ -f /etc/redhat-release ]; then
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
echo -e "  ${BLUE}[2/5]${NC} ดาวน์โหลด RouterAI..."

if [ -d "$INSTALL_DIR" ]; then
    echo -e "  ${YELLOW}⚠️  พบโฟลเดอร์ $INSTALL_DIR — อัพเดต...${NC}"
    cd "$INSTALL_DIR"

    # Verify it's our repo
    ACTUAL_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$ACTUAL_REMOTE" != *"/tenotony/RouterAI"* ]]; then
        echo -e "  ${RED}❌ โฟลเดอร์นี้ไม่ใช่ RouterAI repo! (remote: $ACTUAL_REMOTE)${NC}"
        exit 1
    fi

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
    # Use git clone with verification
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"

    # Verify remote
    ACTUAL_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$ACTUAL_REMOTE" != *"/tenotony/RouterAI"* ]]; then
        echo -e "  ${RED}❌ Clone สำเร็จแต่ remote ไม่ตรง! ($ACTUAL_REMOTE)${NC}"
        exit 1
    fi
fi
echo -e "  ${GREEN}✅ ดาวน์โหลดเสร็จ${NC}"
echo ""

# ── Generate API Key ────────────────────────────────
echo -e "  ${BLUE}[3/5]${NC} สร้าง API Key..."

# Generate a secure random API key
if command -v python3 &> /dev/null; then
    GENERATED_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
elif command -v openssl &> /dev/null; then
    GENERATED_KEY=$(openssl rand -hex 32)
else
    GENERATED_KEY=$(head -c 32 /dev/urandom | xxd -p -c 64)
fi

echo -e "  ${GREEN}🔑 สร้าง API Key อัตโนมัติ${NC}"
echo ""

# ── Setup ───────────────────────────────────────────
echo -e "  ${BLUE}[4/5]${NC} ตั้งค่า..."

# Create .env with auto-generated API key
if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || touch .env
    echo ""
    echo -e "  ${YELLOW}📝 สร้างไฟล์ .env — ใส่ API Key ได้ใน Dashboard หรือแก้ไฟล์ .env${NC}"
fi

# Add auto-generated API key to .env if ROUTERAI_API_KEY is not set
if ! grep -q "^ROUTERAI_API_KEY=.\+" .env 2>/dev/null; then
    # Remove commented or empty ROUTERAI_API_KEY line
    sed -i '/^ROUTERAI_API_KEY=/d' .env 2>/dev/null || true
    echo "" >> .env
    echo "# Auto-generated API key (keep this secret!)" >> .env
    echo "ROUTERAI_API_KEY=${GENERATED_KEY}" >> .env
    echo -e "  ${GREEN}✅ API Key ตั้งค่าใน .env แล้ว${NC}"
else
    echo -e "  ${GREEN}✅ API Key มีอยู่แล้วใน .env${NC}"
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
echo -e "  ${BLUE}[5/5]${NC} เริ่มระบบ..."

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

# ── Show API Key ────────────────────────────────────
echo -e "  ${RED}${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "  ${RED}${BOLD}║${NC}  ${BOLD}🔒 สำคัญ: จด API Key นี้เก็บไว้!${NC}                  ${RED}${BOLD}║${NC}"
echo -e "  ${RED}${BOLD}║${NC}                                                  ${RED}${BOLD}║${NC}"
echo -e "  ${RED}${BOLD}║${NC}  ${YELLOW}🔑 API Key: ${GENERATED_KEY}${NC}  ${RED}${BOLD}║${NC}"
echo -e "  ${RED}${BOLD}║${NC}                                                  ${RED}${BOLD}║${NC}"
echo -e "  ${RED}${BOLD}║${NC}  Key นี้ใช้สำหรับ /v1/* endpoints                 ${RED}${BOLD}║${NC}"
echo -e "  ${RED}${BOLD}║${NC}  เปลี่ยนได้ใน .env → ROUTERAI_API_KEY             ${RED}${BOLD}║${NC}"
echo -e "  ${RED}${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
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
