#!/bin/bash
# ============================================
#  🔀 RouterAI — One-Command Installer
#  ใช้: curl -fsSL https://raw.githubusercontent.com/tenotony/RouterAI/main/install.sh | bash
# ============================================

set -e

REPO="https://github.com/tenotony/RouterAI.git"
DEFAULT_DIR="RouterAI"

# Colors
B='\033[1m'; G='\033[0;32m'; Y='\033[0;33m'; R='\033[0;31m'; C='\033[0;36m'; N='\033[0m'

echo ""
echo -e "  ${C}╔══════════════════════════════════════════════╗${N}"
echo -e "  ${C}║${N}  ${B}🔀 RouterAI v3.5 — One-Command Install${N}       ${C}║${N}"
echo -e "  ${C}║${N}  รวม AI ฟรี 26 providers สำหรับ OpenClaw 🇹🇭  ${C}║${N}"
echo -e "  ${C}╚══════════════════════════════════════════════╝${N}"
echo ""

# ── 0. เลือกที่ติดตั้ง ──────────────────────────
echo -e "  ${C}[0/5]${N} เลือกที่ติดตั้ง..."
echo ""
echo -e "  ${B}ไดร์ที่มีพื้นที่:${N}"
# แสดงพื้นที่ว่างของแต่ละ mount point
df -h 2>/dev/null | grep -E '^/dev/' | awk '{printf "    %s  —  free: %s of %s\n", $6, $4, $2}' || true
# Windows/WSL drives
for d in /mnt/c /mnt/d /mnt/e /mnt/f; do
    [ -d "$d" ] && echo -e "    ${C}$d${N}  (Windows drive)"
done
echo ""
read -p "  📁 ใส่ path ที่จะติดตั้ง (กด Enter = โฟลเดอร์ปัจจุบัน): " INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$(pwd)/$DEFAULT_DIR}"

# สร้างโฟลเดอร์ถ้ายังไม่มี
mkdir -p "$INSTALL_DIR" 2>/dev/null || {
    echo -e "  ${R}❌ ไม่สามารถสร้างโฟลเดอร์ $INSTALL_DIR ได้${N}"
    exit 1
}

# แปลงเป็น absolute path
INSTALL_DIR="$(cd "$INSTALL_DIR" 2>/dev/null && pwd)" || INSTALL_DIR="$(realpath "$INSTALL_DIR" 2>/dev/null || echo "$INSTALL_DIR")"

echo -e "  ${G}✅ จะติดตั้งที่: ${INSTALL_DIR}${N}"
echo ""

cd "$INSTALL_DIR"

# ── 1. Docker ──────────────────────────────────
echo -e "  ${C}[1/5]${N} ตรวจสอบ Docker..."
if ! command -v docker &>/dev/null; then
    echo -e "  ${Y}⚠️  ไม่พบ Docker — กำลังติดตั้ง...${N}"
    if [ -f /etc/debian_version ]; then
        curl -fsSL https://get.docker.com | sudo sh
    elif [ -f /etc/redhat-release ]; then
        curl -fsSL https://get.docker.com | sudo sh
    else
        echo -e "  ${R}❌ ติดตั้ง Docker ด้วยตนเอง: https://docs.docker.com/get-docker/${N}"
        exit 1
    fi
    sudo usermod -aG docker $USER 2>/dev/null || true
    echo -e "  ${G}✅ Docker ติดตั้งแล้ว${N}"
else
    echo -e "  ${G}✅ Docker: $(docker --version | awk '{print $3}')${N}"
fi

if ! docker compose version &>/dev/null 2>&1; then
    echo -e "  ${Y}⚠️  กำลังติดตั้ง docker compose plugin...${N}"
    if [ -f /etc/debian_version ]; then
        sudo apt-get install -y docker-compose-plugin 2>/dev/null || true
    fi
fi
echo ""

# ── 2. Download ────────────────────────────────
echo -e "  ${C}[2/5]${N} ดาวน์โหลด RouterAI..."

# Check if already has routerai files here
if [ -f "src/server.py" ] && [ -f "providers.json" ]; then
    echo -e "  ${Y}📁 พบ RouterAI อยู่แล้ว — อัพเดต...${N}"
    [ -f .env ] && cp .env /tmp/routerai.env.bak
    [ -d data ] && cp -r data /tmp/routerai.data.bak 2>/dev/null || true
    git pull origin main 2>/dev/null || git fetch origin && git reset --hard origin/main
    [ -f /tmp/routerai.env.bak ] && cp /tmp/routerai.env.bak .env
    [ -d /tmp/routerai.data.bak ] && cp -r /tmp/routerai.data.bak data 2>/dev/null || true
    rm -f /tmp/routerai.env.bak; rm -rf /tmp/routerai.data.bak
elif [ -d "$DEFAULT_DIR" ] || [ -d ".git" ]; then
    echo -e "  ${Y}📁 พบโฟลเดอร์ — อัพเดต...${N}"
    [ -f .env ] && cp .env /tmp/routerai.env.bak
    [ -d data ] && cp -r data /tmp/routerai.data.bak 2>/dev/null || true
    git pull origin main 2>/dev/null || git fetch origin && git reset --hard origin/main
    [ -f /tmp/routerai.env.bak ] && cp /tmp/routerai.env.bak .env
    [ -d /tmp/routerai.data.bak ] && cp -r /tmp/routerai.data.bak data 2>/dev/null || true
    rm -f /tmp/routerai.env.bak; rm -rf /tmp/routerai.data.bak
else
    git clone --depth 1 "$REPO" .
fi
echo -e "  ${G}✅ ดาวน์โหลดเสร็จ${N}"
echo ""

# ── 3. Config ──────────────────────────────────
echo -e "  ${C}[3/5]${N} ตั้งค่า..."

# Generate API key
if command -v python3 &>/dev/null; then
    KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
else
    KEY=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p -c 64)
fi

# Create .env
if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || true
fi

# Set API key if not already set
if ! grep -q "^ROUTERAI_API_KEY=.\{10,\}" .env 2>/dev/null; then
    sed -i '/^ROUTERAI_API_KEY=/d' .env 2>/dev/null || true
    echo "ROUTERAI_API_KEY=$KEY" >> .env
    echo -e "  ${G}🔑 API Key สร้างแล้ว${N}"
fi

mkdir -p data/cache
chmod +x scripts/*.sh 2>/dev/null || true
echo -e "  ${G}✅ ตั้งค่าเรียบร้อย${N}"
echo ""

# ── 4. Build ───────────────────────────────────
echo -e "  ${C}[4/5]${N} Build Docker image..."
docker compose -f docker-compose.simple.yml down 2>/dev/null || true
docker compose -f docker-compose.simple.yml build --no-cache 2>&1 | tail -5
echo -e "  ${G}✅ Build เสร็จ${N}"
echo ""

# ── 5. Start ───────────────────────────────────
echo -e "  ${C}[5/5]${N} เริ่มระบบ..."
docker compose -f docker-compose.simple.yml up -d 2>&1

echo -e "  ${Y}⏳ รอระบบเริ่ม...${N}"
sleep 8

if docker compose -f docker-compose.simple.yml ps 2>/dev/null | grep -q "Up\|healthy"; then
    echo -e "  ${G}✅ RouterAI รันแล้ว!${N}"
else
    echo -e "  ${Y}⚠️  กำลังเริ่ม... ดู log: docker compose -f docker-compose.simple.yml logs -f${N}"
fi
echo ""

# ── Done! ──────────────────────────────────────
PORT=$(grep "^ROUTERAI_PORT=" .env 2>/dev/null | cut -d= -f2 || echo "8900")

echo -e "  ${G}${B}╔══════════════════════════════════════════════╗${N}"
echo -e "  ${G}${B}║${N}        ✅ ติดตั้งเสร็จ! RouterAI พร้อมใช้ 🎉    ${G}${B}║${N}"
echo -e "  ${G}${B}╚══════════════════════════════════════════════╝${N}"
echo ""
echo -e "  ${B}📊 Dashboard:${N}  ${C}http://localhost:${PORT}${N}"
echo -e "  ${B}🔑 API Key:${N}    ${Y}${KEY}${N}"
echo ""
echo -e "  ${B}📝 ขั้นตอนต่อไป:${N}"
echo -e "     ${C}1.${N} เปิด Dashboard → ใส่ API Key อย่างน้อย 1 ตัว"
echo -e "     ${C}2.${N} แนะนำ: ${C}https://console.groq.com/keys${N} (ฟรี, เร็วสุด)"
echo -e "     ${C}3.${N} Dashboard → \"🤖 เชื่อม OpenClaw\" → คัดลอก Config"
echo -e "     ${C}4.${N} วางใน ~/.openclaw/openclaw.json → openclaw restart"
echo ""
echo -e "  ${B}🔧 คำสั่ง:${N}"
echo -e "     ${C}cd ${INSTALL_DIR}${N}"
echo -e "     ${C}docker compose -f docker-compose.simple.yml logs -f${N}    ดู log"
echo -e "     ${C}docker compose -f docker-compose.simple.yml restart${N}    รีสตาร์ท"
echo -e "     ${C}docker compose -f docker-compose.simple.yml down${N}       หยุด"
echo ""
