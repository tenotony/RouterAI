# 🔀 RouterAI

> **รวม AI ฟรีทุกตัวมาไว้ที่เดียว** — OpenAI-compatible proxy with auto-failover, rate limiting, and Thai dashboard

[![CI](https://github.com/tenotony/RouterAI/actions/workflows/ci.yml/badge.svg)](https://github.com/tenotony/RouterAI/actions/workflows/ci.yml)

🌐 Dashboard ภาษาไทย · ⚡ Auto-Failover · 🆓 โมเดลฟรีเพียบ · 🔒 ปลอดภัย 100%

---

## ✨ ฟีเจอร์

| ฟีเจอร์ | คำอธิบาย |
|---------|-----------|
| 🔄 **Auto-Failover** | ถ้าตัวไหนล่ม สลับไปตัวอื่นอัตโนมัติ |
| 🏎️ **Hedge Race** | ยิง top-2 providers พร้อมกัน เลือกตัวเร็วกว่า |
| 🏆 **Category Winners** | เรียนรู้ว่า model ไหนเก่ง code/thai/math/tools |
| ⚡ **Live Score EMA** | อัพเดท success rate ทุก request แบบ real-time |
| 🎛️ **Smart Aliases** | routerai/auto, /fast, /tools, /thai, /code |
| 📊 **Exam System** | สอบ model ก่อนใช้งานจริง (8 ข้อ ผ่าน ≥ 70%) |
| 📏 **Capacity Learning** | เรียนรู้ token capacity จริงของแต่ละ model |
| 📈 **Rate Limit Learning** | อ่าน header + parse 429 เรียนรู้ TPM/TPD |
| ⏳ **Exponential Cooldown** | 30s → 1m → 2 → 4 → 8 min auto-reset |
| 💾 **Response Cache** | จำคำตอบเดิม ไม่ต้องเสียตังค์เรียกซ้ำ |
| 🚦 **Rate Limiting** | จำกัด requests ต่อ client ป้องกัน abuse |
| 📊 **Dashboard ไทย** | จัดการทุกอย่างผ่านหน้าเว็บ |
| 🔌 **20 Providers** | Groq, MiMo, Gemini, Cerebras, DeepSeek, SambaNova, LLM7, ฯลฯ |
| 📊 **Leaderboard** | ดู ranking model ที่ดีที่สุด |
| 🔍 **Full Observability** | Request ID trace ทั้ง chain |
| 🤖 **OpenClaw Ready** | สร้าง config เชื่อม OpenClaw 1 คลิก |
| 🔒 **Auth Support** | ตั้ง API Key ป้องกัน endpoint |
| 🐳 **Docker** | deploy ง่าย container เดียว |

---

## ⚡ ติดตั้งเร็ว (1 คำสั่ง)

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/tenotony/RouterAI/main/scripts/install-docker.sh | bash
```

สคริปต์จะ:
- ✅ ตรวจสอบ/ติดตั้ง Docker อัตโนมัติ
- ✅ ดาวน์โหลดโค้ด
- ✅ สร้างไฟล์ตั้งค่า
- ✅ เริ่มระบบด้วย Docker Compose

### Windows

```powershell
git clone https://github.com/tenotony/RouterAI.git
cd RouterAI
.\scripts\setup.bat
```

### Manual (ไม่ใช้ Docker)

```bash
git clone https://github.com/tenotony/RouterAI.git
cd RouterAI
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python src/server.py
```

---

## 🚀 ใช้งาน

### เปิด Dashboard

```
http://localhost:8900
```

> **port เดียวจบ** — ทั้ง Dashboard + API อยู่ที่ port 8900

### แท็บ Dashboard

| แท็บ | หน้าที่ |
|------|---------|
| 📊 แดชบอร์ด | ดูสถานะทุก Provider + สถิติ |
| 🔌 ผู้ให้บริการ | ดูรายละเอียด + ทดสอบแต่ละตัว |
| 🔑 จัดการ API Key | กรอก Key สำหรับแต่ละเจ้า |
| 🤖 เชื่อม OpenClaw | สร้าง Config อัตโนมัติ 1 คลิก |
| 🧠 เลือกโมเดล | ดูโมเดลทั้งหมด ฟิลเตอร์ฟรี/จ่ายเงิน |
| ⚙️ ตั้งค่า | Cache, Failover, Budget, Rate Limit |
| 🩺 ตรวจสอบระบบ | สถานะสุขภาพระบบทั้งหมด |

---

## 🔗 เชื่อมต่อกับ OpenClaw

1. ใส่ API Key อย่างน้อย 1 ตัว (แนะนำ Groq)
2. Dashboard → แท็บ "เชื่อม OpenClaw" → เลือก Provider + Model → กดปุ่ม ⚡
3. คัดลอก Config → วางใน `~/.openclaw/openclaw.json`
4. รัน `openclaw restart`

หรือแก้ไข `~/.openclaw/openclaw.json` เอง:

```json
{
  "llm": {
    "provider": "openai",
    "baseUrl": "http://127.0.0.1:8900/v1",
    "apiKey": "routerai",
    "model": "groq/llama-3.3-70b-versatile"
  }
}
```

---

## 🔑 Provider ที่รองรับ

| Provider | สมัคร | ฟรี? | ความเร็ว |
|----------|-------|------|---------|
| ⚡ Groq | [console.groq.com/keys](https://console.groq.com/keys) | ✅ | ⭐⭐⭐⭐⭐ |
| 🟠 Xiaomi MiMo | [xiaomi.com/mimo](https://xiaomi.com/mimo) | ✅ | ⭐⭐⭐⭐ |
| 🟢 Google Gemini | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | ✅ | ⭐⭐⭐⭐ |
| 🚀 Cerebras | [cloud.cerebras.ai](https://cloud.cerebras.ai) | ✅ | ⭐⭐⭐⭐⭐ |
| 🌐 OpenRouter | [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) | ✅ | ⭐⭐⭐ |
| 🟣 Mistral | [console.mistral.ai](https://console.mistral.ai/api-keys/) | ✅ | ⭐⭐⭐ |
| 🔵 NVIDIA | [build.nvidia.com](https://build.nvidia.com/explore/discover) | ✅ | ⭐⭐⭐⭐ |
| 💎 DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) | ❌ | ⭐⭐⭐⭐ |
| 🇨🇳 SiliconFlow | [cloud.siliconflow.cn](https://cloud.siliconflow.cn) | ✅ | ⭐⭐⭐ |
| 🪂 Chutes AI | [chutes.ai](https://chutes.ai) | ✅ | ⭐⭐⭐ |
| 🤝 Together AI | [api.together.xyz](https://api.together.xyz/settings/api-keys) | $5 credit | ⭐⭐⭐ |
| 🏠 Ollama | [ollama.com](https://ollama.com) | ✅ local | ⭐⭐⭐⭐ |

> 💡 **แนะนำ:** สมัครแค่ **Groq** ตัวเดียวก็เริ่มใช้ได้เลย!

---

## 📚 API Documentation

RouterAI มี API docs อัตโนมัติจาก FastAPI:

```
http://localhost:8900/docs      # Swagger UI (interactive)
http://localhost:8900/redoc     # ReDoc (สวยๆ)
```

---

## 🏗️ สถาปัตยกรรม

```
Request → RouterAI Server (port 8900)
          │
          ├─ /v1/*    → OpenAI-compatible proxy
          ├─ /api/*   → Dashboard API
          ├─ /        → Dashboard UI
          └─ /health  → Health check
               │
               ├─ 1) Response Cache Check
               │     └─ HIT → return cached
               │
               ├─ 2) Rate Limit Check
               │     └─ EXCEEDED → 429
               │
               ├─ 3) Smart Routing
               │     ├─ Latency scoring
               │     ├─ Error tracking (exponential backoff)
               │     └─ Auto-failover
               │
               ├─ 4) Provider Pool
               │     ├─ Groq (priority: 100)
               │     ├─ Xiaomi MiMo (priority: 98)
               │     ├─ Cerebras (priority: 95)
               │     └─ ...more providers
               │
               └─ 5) Response → Cache → Track → Return
```

---

## 🔧 พัฒนาต่อ (สำหรับ Dev)

```bash
# ติดตั้ง + รัน
./dev.sh install      # ติดตั้ง deps + dev tools
./dev.sh run          # รัน unified server
./dev.sh test         # รัน tests
./dev.sh lint         # ตรวจ code quality
./dev.sh format       # จัด format อัตโนมัติ

# Docker
./dev.sh docker-build # build image
./dev.sh docker-run   # run with docker compose
./dev.sh docker-stop  # stop containers
```

### โครงสร้างโปรเจกต์

```
RouterAI/
├── src/
│   └── server.py          ← Unified server (proxy + dashboard + API)
├── web/
│   └── index.html         ← Dashboard UI (vanilla JS, Thai)
├── tests/
│   └── test_core.py       ← Unit tests (23 tests)
├── scripts/
│   ├── install.sh         ← Auto installer (venv)
│   ├── install-docker.sh  ← Auto installer (Docker)
│   ├── setup.bat          ← Windows setup
│   ├── update.sh          ← Update & restart
│   └── entrypoint.sh      ← Docker entrypoint
├── .github/
│   └── workflows/
│       └── ci.yml         ← GitHub Actions CI
├── docker-compose.yml     ← Docker deployment
├── Dockerfile             ← Docker image
├── requirements.txt       ← Python deps
├── providers.json         ← Provider config
├── pyproject.toml         ← ruff + pytest config
├── dev.sh                 ← Development script
├── .env.example           ← Environment template
├── README.md              ← คุณกำลังอ่านอยู่
└── ROADMAP.md             ← Development plan
```

---

## 🔒 ความปลอดภัย

- ✅ รันบนเครื่องคุณ ไม่ส่งข้อมูลให้ใคร
- ✅ ไม่มี tracking / analytics
- ✅ API Key เก็บเฉพาะเครื่องคุณ
- ✅ โค้ดเปิดทั้งหมด (MIT License)
- ✅ Rate limiting ป้องกัน abuse
- ✅ Auth support (ตั้ง `ROUTERAI_API_KEY` env var)

---

## ❓ Troubleshooting

| ปัญหา | วิธีแก้ |
|-------|--------|
| Docker ไม่เริ่ม | ตรวจสอบ: `docker --version` |
| Port ถูกใช้ | เปลี่ยน `ROUTERAI_PORT` ใน `.env` |
| API Key ไม่ทำงาน | กด "ทดสอบ" ใน Dashboard เพื่อเช็ค |
| OpenClaw เชื่อมไม่ได้ | รัน `openclaw restart` หลังตั้งค่า |

---

## 🤝 ชุมชน

- [เปิด Issue](https://github.com/tenotony/RouterAI/issues)
- [เข้ากลุ่ม Facebook](https://www.facebook.com/groups/1248346110734837)

---

## 📄 License

MIT License — ใช้ได้ฟรี แก้ไขได้ แจกจ่ายได้

---

สร้างด้วย ❤️ เพื่อคนไทย 🇹🇭
