#!/bin/bash
# ============================================
#  🏢 RouterAI + OpenClaw Setup
#  ติดตั้ง RouterAI และเชื่อมต่อกับ OpenClaw
# ============================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════╗"
echo "║  🏢 RouterAI + OpenClaw Organization     ║"
echo "║  CEO → Workers → RouterAI → Knowledge   ║"
echo "╚══════════════════════════════════════════╝"
echo -e "${NC}"

# Step 1: Check prerequisites
echo -e "${YELLOW}[1/6] ตรวจสอบ prerequisites...${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker ไม่พบ — กรุณาติดตั้ง Docker ก่อน${NC}"
    echo "   curl -fsSL https://get.docker.com | sh"
    exit 1
fi
echo -e "${GREEN}✅ Docker พบแล้ว${NC}"

if ! command -v openclaw &> /dev/null; then
    echo -e "${YELLOW}⚠️  OpenClaw ไม่พบใน PATH — ข้ามขั้นตอน config${NC}"
    SKIP_OPENCLAW=true
else
    echo -e "${GREEN}✅ OpenClaw พบแล้ว${NC}"
    SKIP_OPENCLAW=false
fi

# Step 2: Setup .env
echo -e "${YELLOW}[2/6] ตั้งค่า environment...${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

if [ ! -f .env ]; then
    cp .env.example .env
    echo -e "${GREEN}✅ สร้าง .env จาก .env.example แล้ว${NC}"
    echo -e "${YELLOW}   ⚠️  กรุณาใส่ API Key อย่างน้อย 1 ตัวใน .env${NC}"
    echo -e "${YELLOW}   แนะนำ: GROQ_API_KEY (สมัครฟรีที่ console.groq.com)${NC}"
else
    echo -e "${GREEN}✅ .env มีอยู่แล้ว${NC}"
fi

# Step 3: Start Docker
echo -e "${YELLOW}[3/6] เริ่ม RouterAI ด้วย Docker...${NC}"

docker compose down 2>/dev/null || true
docker compose up -d --build

echo -e "${GREEN}✅ RouterAI เริ่มทำงานแล้ว${NC}"
echo -e "${CYAN}   📡 Proxy: http://127.0.0.1:8900${NC}"
echo -e "${CYAN}   📊 Dashboard: http://127.0.0.1:8899${NC}"

# Step 4: Wait for health
echo -e "${YELLOW}[4/6] รอ RouterAI พร้อมใช้งาน...${NC}"

for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8900/health > /dev/null 2>&1; then
        echo -e "${GREEN}✅ RouterAI พร้อมใช้งาน!${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${YELLOW}⚠️  RouterAI ยังไม่พร้อม — ลองเช็คด้วย: docker compose logs${NC}"
    fi
    sleep 1
done

# Step 5: Setup knowledge base
echo -e "${YELLOW}[5/6] สร้างโครงสร้าง Knowledge Base...${NC}"

mkdir -p knowledge-base/memory
mkdir -p knowledge-base/documents
mkdir -p knowledge-base/data
mkdir -p knowledge-base/projects

echo -e "${GREEN}✅ Knowledge Base พร้อม${NC}"

# Step 6: OpenClaw config
echo -e "${YELLOW}[6/6] เชื่อมต่อกับ OpenClaw...${NC}"

if [ "$SKIP_OPENCLAW" = "true" ]; then
    echo -e "${YELLOW}⚠️  ข้ามขั้นตอน OpenClaw config (ไม่พบ openclaw)${NC}"
    echo -e "${CYAN}   สามารถตั้งค่าเองได้ทีหลังจาก openclaw-config.json${NC}"
else
    echo -e "${GREEN}✅ พบ openclaw-config.json แล้ว${NC}"
    echo -e "${CYAN}   กรุณาเปิด Dashboard ที่ http://127.0.0.1:8899${NC}"
    echo -e "${CYAN}   ไปที่แท็บ 'เชื่อม OpenClaw' เพื่อสร้าง config อัตโนมัติ${NC}"
fi

# Summary
echo ""
echo -e "${CYAN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}🎉 ติดตั้งเสร็จสิ้น!${NC}"
echo -e "${CYAN}══════════════════════════════════════════${NC}"
echo ""
echo -e "${CYAN}🏢 สถาปัตยกรรม:${NC}"
echo -e "   👤 Human (คุณ)"
echo -e "   └─ 🧠 CEO Agent (ผู้บริหาร)"
echo -e "      ├─ ✍️ น้องเขียน (Writer)"
echo -e "      ├─ 💻 น้องโค้ด (Coder)"
echo -e "      ├─ 🔍 น้องสืบ (Researcher)"
echo -e "      ├─ 📊 น้องข้อมูล (Data)"
echo -e "      └─ ⚙️ น้องจัดการ (Ops)"
echo -e "      └─ 🔄 RouterAI (เครื่องมือช่วย)"
echo -e "      └─ 🧠 Knowledge Base (คลังความรู้)"
echo ""
echo -e "${YELLOW}ขั้นตอนถัดไป:${NC}"
echo -e "   1. เปิด Dashboard: http://127.0.0.1:8899"
echo -e "   2. ใส่ API Key อย่างน้อย 1 ตัว (แนะนำ Groq)"
echo -e "   3. ไปที่แท็บ 'เชื่อม OpenClaw' → กด ⚡"
echo -e "   4. คัดลอก Config → วางใน ~/.openclaw/openclaw.json"
echo -e "   5. รัน: openclaw restart"
echo ""
