@echo off
chcp 65001 >nul 2>&1
echo.
echo   ╔══════════════════════════════════════════╗
echo   ║  🔀 RouterAI — Windows Setup             ║
echo   ║  รวม AI ฟรีสำหรับ OpenClaw 🇹🇭            ║
echo   ╚══════════════════════════════════════════╝
echo.

REM Check Docker
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ❌ ไม่พบ Docker Desktop
    echo   กรุณาติดตั้งจาก: https://www.docker.com/products/docker-desktop/
    echo   แล้วรันสคริปต์นี้อีกครั้ง
    pause
    exit /b 1
)

docker compose version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ❌ ไม่พบ Docker Compose
    echo   กรุณาอัพเดต Docker Desktop ให้เป็นเวอร์ชั่นล่าสุด
    pause
    exit /b 1
)

echo   ✅ Docker พร้อมใช้
echo.

REM Setup files
echo   [1/3] ตั้งค่าไฟล์...
if not exist .env copy .env.example .env >nul 2>&1
if not exist api_keys.json echo {} > api_keys.json
if not exist proxy_config.json echo {} > proxy_config.json
if not exist data mkdir data
if not exist data\cache mkdir data\cache
echo   ✅ ตั้งค่าเรียบร้อย
echo.

REM Start
echo   [2/3] สร้างและรัน Docker containers...
docker compose down -v 2>nul
docker compose build --no-cache
docker compose up -d
echo.

echo   [3/3] ตรวจสอบสถานะ...
timeout /t 5 /nobreak >nul
docker compose ps
echo.

echo   ╔══════════════════════════════════════════╗
echo   ║        ✅ ติดตั้งเสร็จเรียบร้อย! 🎉        ║
echo   ╚══════════════════════════════════════════╝
echo.
echo   📝 ขั้นตอนต่อไป:
echo.
echo   1. เปิด Dashboard: http://localhost:8899
echo   2. ไปหน้า "🔑 จัดการ API Key" ใส่ Key อย่างน้อย 1 ตัว
echo   3. ไปหน้า "🤖 เชื่อม OpenClaw" สร้าง Config
echo   4. วาง Config ใน %USERPROFILE%\.openclaw\openclaw.json
echo   5. รัน openclaw restart
echo.
echo   💡 แนะนำ: สมัคร Groq (ฟรี) ที่ https://console.groq.com/keys
echo.
pause
