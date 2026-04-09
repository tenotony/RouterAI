# 🔀 RouterAI

> **รวม AI ฟรี 26 providers มาไว้ที่เดียว** — OpenAI-compatible proxy with auto-failover, smart routing, and Thai dashboard

[![CI](https://github.com/tenotony/RouterAI/actions/workflows/ci.yml/badge.svg)](https://github.com/tenotony/RouterAI/actions/workflows/ci.yml)

🌐 Dashboard ภาษาไทย · ⚡ Auto-Failover · 🏎️ Hedge Race · 🆓 26 ฟรี Providers · 🔒 ปลอดภัย 100%

---

## ⚡ ติดตั้ง (1 คำสั่ง)

```bash
curl -fsSL https://raw.githubusercontent.com/tenotony/RouterAI/main/install.sh | bash
```

หรือ manual:

```bash
git clone https://github.com/tenotony/RouterAI.git
cd RouterAI
docker compose -f docker-compose.simple.yml up -d --build
```

**เสร็จ!** เปิด Dashboard: **http://localhost:8900**

> สมัคร Groq (ฟรี 1 นาที) → ใส่ API Key ใน Dashboard → ใช้ได้เลย
> https://console.groq.com/keys

---

## ✨ ฟีเจอร์

| ฟีเจอร์ | คำอธิบาย |
|---------|-----------|
| 🔄 **Auto-Failover** | ถ้าตัวไหนล่ม สลับไปตัวอื่นอัตโนมัติ |
| 🏎️ **Hedge Race** | ยิง top-2 providers พร้อมกัน เลือกตัวเร็วกว่า |
| 🏆 **Category Winners** | เรียนรู้ว่า model ไหนเก่ง code/thai/math/tools (11 categories) |
| ⚡ **Live Score EMA** | อัพเดท success rate ทุก request แบบ real-time |
| 🎛️ **Smart Aliases** | `routerai/auto`, `/fast`, `/tools`, `/thai`, `/code`, `/math`, `/consensus` |
| 🤝 **Consensus Mode** | ยิง 3 model พร้อมกัน เลือกคำตอบที่ consensus |
| 📊 **Exam System** | สอบ model ก่อนใช้งานจริง (8 ข้อ ผ่าน ≥ 70%) |
| 📏 **Capacity Learning** | เรียนรู้ token capacity จริงของแต่ละ model (p90) |
| 📈 **Rate Limit Learning** | อ่าน header + parse 429 เรียนรู้ TPM/TPD |
| ⏳ **Exponential Cooldown** | 30s → 1m → 2 → 4 → 8 min auto-reset |
| ⏱️ **Dynamic Timeout** | ปรับ timeout ตาม body size + estimated tokens |
| 💾 **Response Cache** | จำคำตอบเดิม ไม่ต้องเสียตังค์เรียกซ้ำ |
| 🚦 **Rate Limiting** | จำกัด requests ต่อ client ป้องกัน abuse |
| 🔍 **Skip Reasons** | 503 บอกเหตุผลทุก provider ที่ถูกข้าม |
| 🔄 **Relaxed Retry** | เมื่อทุกตัวพลาด ลอง provider ที่ถูก skip |
| 📊 **Dashboard ไทย** | จัดการทุกอย่างผ่านหน้าเว็บ |
| 🔌 **26 Providers** | Groq, NVIDIA, Cerebras, Mistral, SambaNova, ฯลฯ |
| 📊 **Leaderboard** | ดู ranking model ที่ดีที่สุด |
| 🔍 **Full Observability** | Request ID trace ทั้ง chain |
| 🤖 **OpenClaw Ready** | สร้าง config เชื่อม OpenClaw 1 คลิก |
| 🔒 **Auth Support** | ตั้ง API Key ป้องกัน endpoint |
| 🐳 **Docker** | deploy ง่าย container เดียว |

---

## 🔗 เชื่อมต่อกับ OpenClaw

1. เปิด Dashboard → ใส่ API Key อย่างน้อย 1 ตัว
2. แท็บ "🤖 เชื่อม OpenClaw" → เลือก Provider + Model → กด ⚡
3. คัดลอก Config → วางใน `~/.openclaw/openclaw.json`
4. รัน `openclaw restart`

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

### Smart Model Aliases

```
model: "routerai/auto"        # Smart routing (default)
model: "routerai/fast"        # เน้น latency ต่ำ
model: "routerai/tools"       # เน้น tool calling
model: "routerai/thai"        # เน้นภาษาไทย
model: "routerai/code"        # เน้นเขียนโค้ด
model: "routerai/math"        # เน้นคำนวณ
model: "routerai/consensus"   # 3 models parallel
model: "groq/llama-3.3-70b"   # Direct provider
```

---

## 🔌 26 Providers

### ⭐ แนะนำ (ฟรี ไม่ต้องบัตรเครดิต)

| Provider | ฟรี Limit | ความเร็ว | สมัคร |
|----------|----------|---------|-------|
| ⚡ **Groq** | 14,400 RPD × 7 models | ⭐⭐⭐⭐⭐ | [console.groq.com](https://console.groq.com/keys) |
| 🔵 **NVIDIA** | 1,000 credits (lifetime) 168+ models | ⭐⭐⭐⭐⭐ | [build.nvidia.com](https://build.nvidia.com) |
| 🚀 **Cerebras** | 1M tokens/day | ⭐⭐⭐⭐⭐ | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| 🟣 **Mistral** | 1B tok/mo, 60+ models | ⭐⭐⭐⭐⭐ | [console.mistral.ai](https://console.mistral.ai) |
| 🟤 **SambaNova** | 30 RPM × 12 models | ⭐⭐⭐⭐⭐ | [cloud.sambanova.ai](https://cloud.sambanova.ai) |
| 🪂 **Chutes AI** | Unlimited (community GPU) | ⭐⭐⭐⭐⭐ | [chutes.ai](https://chutes.ai) |

### 🆓 Free ถาวร

| Provider | ฟรี Limit | สมัคร |
|----------|----------|-------|
| 🆓 **LLM7.io** | 30 RPM, DeepSeek R1 | [token.llm7.io](https://token.llm7.io) |
| 🇪🇺 **Scaleway** | 1M tokens lifetime | [console.scaleway.com](https://console.scaleway.com) |
| 🟢 **Google Gemini** | 5-15 RPM, 1M context | [aistudio.google.com](https://aistudio.google.com/apikey) |
| 🧠 **Z.AI (GLM)** | 1M context ฟรี | [z.ai](https://z.ai/manage-apikey/apikey-list) |
| 🐙 **GitHub Models** | GPT-4o ฟรี 50-150 RPD | [github.com/settings/tokens](https://github.com/settings/tokens) |
| 💎 **Cohere** | 1K/เดือน | [dashboard.cohere.com](https://dashboard.cohere.com/api-keys) |
| 🌸 **Pollinations** | GPT-5/Claude/Gemini | [enter.pollinations.ai](https://enter.pollinations.ai) |
| ☁️ **Cloudflare** | 10K Neurons/วัน | [dash.cloudflare.com](https://dash.cloudflare.com/profile/api-tokens) |
| 🇨🇳 **SiliconFlow** | 50 RPD, Qwen/DeepSeek | [cloud.siliconflow.cn](https://cloud.siliconflow.cn) |
| 🌐 **OpenRouter** | 50 RPD, 30+ models | [openrouter.ai](https://openrouter.ai/settings/keys) |
| 🏠 **Ollama** | Unlimited (local) | [ollama.com](https://ollama.com) |

### 💳 Free Credits

| Provider | เครดิต | สมัคร |
|----------|--------|-------|
| 🤝 **Together AI** | $25 signup | [api.together.xyz](https://api.together.xyz/settings/api-keys) |
| 🔮 **Reka AI** | $10/mo auto-refresh | [platform.reka.ai](https://platform.reka.ai) |
| 🐉 **DashScope** | 1M tok × 90 วัน | [bailian.console](https://bailian.console.alibabacloud.com) |
| 🎮 **glhf.chat** | Beta free | [glhf.chat](https://glhf.chat) |
| 🔺 **Hyperbolic** | $1 signup | [app.hyperbolic.ai](https://app.hyperbolic.ai/signup) |
| 🤗 **HuggingFace** | $0.10/mo | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| 🎆 **Fireworks AI** | $1 signup | [fireworks.ai](https://fireworks.ai/account/api-keys) |

### 💰 Paid (ราคาถูก)

| Provider | ราคา | สมัคร |
|----------|------|-------|
| 💎 **DeepSeek** | ถูกมาก | [platform.deepseek.com](https://platform.deepseek.com) |
| 🟠 **Xiaomi MiMo** | ฟรี/จ่าย | [mimo.xiaomi.com](https://mimo.xiaomi.com) |

> 💡 **แนะนำ:** สมัครแค่ **Groq** ตัวเดียวก็เริ่มใช้ได้เลย!

---

## 📊 Dashboard

| แท็บ | หน้าที่ |
|------|---------|
| 📊 แดชบอร์ด | สถานะทุก Provider + สถิติ |
| 🔌 ผู้ให้บริการ | รายละเอียด + ทดสอบแต่ละตัว |
| 🔑 จัดการ API Key | กรอก Key สำหรับแต่ละเจ้า |
| 🤖 เชื่อม OpenClaw | สร้าง Config อัตโนมัติ 1 คลิก |
| 🧠 เลือกโมเดล | โมเดลทั้งหมด ฟิลเตอร์ฟรี/จ่ายเงิน |
| ⚙️ ตั้งค่า | Cache, Failover, Budget, Rate Limit |
| 🩺 ตรวจสอบระบบ | สุขภาพระบบทั้งหมด |

---

## 📚 API Endpoints

```
POST /v1/chat/completions   # OpenAI-compatible (auto routing)
POST /v1/chat/completions   # stream=true → SSE streaming
GET  /v1/models             # รายการ model ที่ผ่านสอบ

GET  /api/leaderboard       # Top performing models
GET  /api/live-score        # EMA scores ทุก provider
GET  /api/category-winners  # ใครชนะแต่ละ category
GET  /api/uptime            # Uptime % per provider
GET  /api/trend             # Requests per hour
GET  /api/routing-log       # Routing decisions ล่าสุด
GET  /api/providers         # Provider status
POST /api/providers/{id}/toggle # เปิด/ปิด provider
GET  /api/stats             # Usage statistics
GET  /api/exams             # Exam history
POST /api/exams/run         # Run exam for a model
GET  /api/capacity          # Learned token capacities
GET  /api/rate-limits       # Learned rate limits
GET  /api/cooldowns         # Cooldown status
GET  /health                # Health check

GET  /docs                  # Swagger UI
GET  /redoc                 # ReDoc
```

---

## 🔧 คำสั่ง Docker

```bash
# เริ่มระบบ
docker compose -f docker-compose.simple.yml up -d --build

# ดู log
docker compose -f docker-compose.simple.yml logs -f

# รีสตาร์ท
docker compose -f docker-compose.simple.yml restart

# หยุดระบบ
docker compose -f docker-compose.simple.yml down

# อัพเดต
git pull origin main
docker compose -f docker-compose.simple.yml up -d --build
```

---

## 🔒 ความปลอดภัย

- ✅ รันบนเครื่องคุณ ไม่ส่งข้อมูลให้ใคร
- ✅ ไม่มี tracking / analytics
- ✅ API Key เก็บเฉพาะเครื่องคุณ (encrypted at rest)
- ✅ โค้ดเปิดทั้งหมด (MIT License)
- ✅ Rate limiting ป้องกัน abuse
- ✅ Docker: non-root user, read-only, no-new-privileges

---

## ❓ Troubleshooting

| ปัญหา | วิธีแก้ |
|-------|--------|
| Docker ไม่เริ่ม | `docker --version` ตรวจสอบ |
| Port ถูกใช้ | เปลี่ยน `ROUTERAI_PORT` ใน `.env` |
| API Key ไม่ทำงาน | กด "ทดสอบ" ใน Dashboard |
| OpenClaw เชื่อมไม่ได้ | รัน `openclaw restart` |
| Container unhealthy | `docker compose -f docker-compose.simple.yml logs -f` |

---

## 📄 License

MIT License — ใช้ได้ฟรี แก้ไขได้ แจกจ่ายได้

---

สร้างด้วย ❤️ เพื่อคนไทย 🇹🇭
