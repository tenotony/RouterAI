# 🔀 RouterAI — Development Roadmap

> **เป้าหมาย:** ทำให้ RouterAI เป็น AI API Router ที่ดีที่สุดสำหรับคนไทย — ใช้งานง่าย ปลอดภัย ประหยัดเงิน

---

## 📌 สถานะปัจจุบัน (Current State)

### ✅ ทำเสร็จแล้ว
- [x] OpenAI-compatible proxy server (FastAPI)
- [x] Dashboard UI ภาษาไทย (dark theme, responsive)
- [x] Auto-failover ระหว่าง providers
- [x] Response cache (ลดการเรียกซ้ำ)
- [x] Provider health tracking
- [x] One-click OpenClaw config generator
- [x] Docker support (docker-compose)
- [x] One-line install script
- [x] 12 providers รวม Xiaomi MiMo
- [x] API Key management via Dashboard
- [x] Model filter (free/paid/fast)
- [x] Provider test (test ทีละตัว + ทั้งหมด)

### ⚠️ สิ่งที่ต้องแก้ไขด่วน (Critical Issues)

| # | ปัญหา | ผลกระทบ | ความยาก |
|---|--------|---------|---------|
| 1 | **Xiaomi MiMo API endpoint** เป็น placeholder — ยังไม่มี URL จริง | MiMo ใช้ไม่ได้ | ต้องรอข้อมูลจาก Xiaomi |

---

## 🎯 Phase 1: แก้ไขพื้นฐาน (Foundation Fixes) ✅ เสร็จแล้ว
> **ระยะเวลา:** 1-2 สัปดาห์

### 1.1 Architecture ให้ถูกต้อง ✅
- [x] รวมเป็นไฟล์เดียว (`server.py`) ที่ทำทั้ง proxy + dashboard API
- [x] Dashboard frontend เรียก `/api/*` ผ่าน proxy ตัวเดียว (port 8900)
- [x] เปลี่ยนเป็น FastAPI (async, เร็วกว่า)
- [x] SQLite แทน file-based stats

### 1.2 Docker ✅
- [x] เปลี่ยน bind mount → named volumes
- [x] Docker health check
- [x] Docker Compose setup

### 1.3 Error Handling
- [x] เพิ่ม retry with exponential backoff ✅
- [x] จัดการ rate limit response (429) — รอแล้ว retry หรือ switch provider ✅
- [x] จัดการ timeout ให้ดีขึ้น ✅
- [x] Streaming failover — stream แตกแล้วลอง provider ถัดไป ✅

---

## 🎯 Phase 2: Security & Auth (ความปลอดภัย)
> **ระยะเวลา:** 1-2 สัปดาห์

### 2.1 API Authentication
ตอนนี้ proxy มี auth แล้ว ✅

- [x] เพิ่ม API key authentication สำหรับ proxy endpoint ✅
- [x] Dashboard login (password หรือ token-based) ✅
- [ ] HTTPS support (auto SSL ด้วย Caddy หรือ nginx)
- [x] Rate limiting per client IP ✅
- [ ] CORS policy ที่เข้มงวดขึ้น (ตอนนี้เปิดทุก origin)

### 2.2 API Key Security
- [x] เข้ารหัส API keys ใน `api_keys.json` (Fernet/AES) ✅
- [x] ไม่แสดง API key เต็มใน Dashboard (แสดงแค่ 4 ตัวท้าย) ✅
- [x] Environment variables มี priority สูงกว่าไฟล์ ✅

---

## 🎯 Phase 3: Smart Routing (ระบบเลือกโมเดลอัจฉริยะ)
> **ระยะเวลา:** 2-3 สัปดาห์

### 3.1 Cost Optimization
- [ ] คำนวณ cost จริงจาก token count (ตอนนี้ไม่ได้ track cost จริง)
- [ ] Budget system ที่ใช้ได้จริง:
  ```
  - จำกัด $/วัน, $/เดือน
  - แจ้งเตือนเมื่อถึง 80% ของ budget
  - Auto-downgrade model เมื่อใกล้หมด budget
  - Dashboard แสดง cost graph
  ```

### 3.2 Smart Model Selection
ตอนนี้เลือกตาม priority ที่ตั้งไว้ล่วงหน้า — ควรฉลาดกว่านี้:

- [ ] **Latency-based routing** — เลือก provider ที่ response เร็วสุดตอนนั้น
- [ ] **Quality scoring** — ให้ user โหวตคำตอบ → ปรับ priority อัตโนมัติ
- [ ] **Task-based routing** — แยก model ตามประเภทงาน:
  ```json
  {
    "coding": "deepseek/deepseek-coder",
    "chat": "groq/llama-3.3-70b-versatile",
    "creative": "google/gemini-2.0-flash",
    "analysis": "deepseek/deepseek-chat"
  }
  ```
- [ ] **Token-aware routing** — ถ้า context ยาว > 100K → เลือก model ที่รองรับ

### 3.3 Advanced Cache
- [ ] Semantic cache — คำถามคล้ายกัน → ใช้ cache เดียวกัน (ใช้ embedding)
- [ ] Cache invalidation ที่ดีขึ้น
- [ ] Cache statistics ใน Dashboard
- [ ] เลือก cache backend: file / Redis / SQLite

---

## 🎯 Phase 4: Dashboard ขั้นสูง (Advanced Dashboard)
> **ระยะเวลา:** 2-3 สัปดาห์

### 4.1 สถิติและกราฟ
- [ ] Token usage graph (รายวัน/สัปดาห์/เดือน) — ใช้ SVG หรือ Chart.js
- [ ] Cost tracking graph
- [ ] Provider uptime chart
- [ ] Response time distribution
- [ ] Most used models ranking

### 4.2 Model Management
- [x] เพิ่ม/ลบ/แก้ไข Custom Provider จาก Dashboard ✅
- [x] Custom provider (ใส่ API base URL + key เอง) ✅
- [x] Model comparison tool — ส่งคำถามเดียวกันไปหลาย model พร้อมกัน ✅
- [x] Prompt testing playground (เหมือน OpenAI Playground) ✅

### 4.3 User Management (Multi-user)
- [ ] User accounts (admin/user roles)
- [ ] Per-user API keys
- [ ] Per-user budget limits
- [ ] Usage quotas per user

### 4.4 Notifications
- [ ] แจ้งเตือนเมื่อ provider ล่ม
- [ ] แจ้งเตือนเมื่อใกล้หมด budget
- [ ] แจ้งเตือนผ่าน LINE / Telegram / Discord webhook

---

## 🎯 Phase 5: เพิ่ม Provider & Model (Expand)
> **ระยะเวลา:** ต่อเนื่อง

### 5.1 Providers ที่ควรเพิ่ม
| Provider | สถานะ | API Type | ฟรี? |
|----------|--------|----------|------|
| Xiaomi MiMo | ⏳ รอ URL จริง | OpenAI-compatible | ✅ |
| Anthropic (Claude) | ❌ ยังไม่มี | ต้อง adapter | ❌ จ่าย |
| Cohere | ❌ ยังไม่มี | OpenAI-compatible | มีฟรี tier |
| Fireworks AI | ❌ ยังไม่มี | OpenAI-compatible | มีฟรี tier |
| Perplexity | ❌ ยังไม่มี | OpenAI-compatible | ❌ จ่าย |
| โมเดลไทย (WangchanBERTa, Typhoon) | ❌ ยังไม่มี | varies | varies |

### 5.2 Multi-modal Support
- [ ] Vision API (ส่งรูปไปให้ model วิเคราะห์)
- [ ] Image generation proxy (DALL-E, Stable Diffusion)
- [ ] Audio/Whisper proxy (transcription)
- [ ] Embedding proxy

### 5.3 Plugin/Skill System
- [ ] Custom middleware pipeline:
  ```
  Request → [Auth] → [Rate Limit] → [Budget Check] → 
  [Cache] → [Model Select] → [Provider] → [Response Transform] → Response
  ```
- [ ] Plugin system สำหรับ custom logic (webhook, logging, etc.)

---

## 🎯 Phase 6: Production Ready
> **ระยะเวลา:** 2-3 สัปดาห์

### 6.1 Performance
- [x] ~~เปลี่ยนจาก Flask → FastAPI~~ ✅ ทำแล้ว
- [x] เปลี่ยนจาก file-based stats → SQLite ✅
- [x] Connection pooling สำหรับ HTTP clients ✅
- [ ] Streaming performance optimization

### 6.2 Deployment
- [ ] One-click deploy บน VPS (DigitalOcean, Vultr, Hetzner)
- [ ] Kubernetes Helm chart
- [ ] Systemd service (สำหรับ bare metal)
- [ ] Auto-update mechanism

### 6.3 Monitoring
- [ ] Prometheus metrics endpoint
- [ ] Grafana dashboard template
- [ ] Structured logging (JSON logs)
- [ ] Error tracking (Sentry integration)

### 6.4 Documentation
- [ ] API documentation (Swagger/OpenAPI)
- [ ] Video tutorial ภาษาไทย
- [ ] Troubleshooting guide
- [ ] Provider-specific setup guides

---

## 🎯 Phase 7: Community & Ecosystem
> **ระยะเวลา:** ต่อเนื่อง

### 7.1 Thai AI Community
- [ ] กลุ่ม Facebook: แชร์ config, ช่วยเหลือกัน
- [ ] Discord server
- [ ] YouTube tutorial series

### 7.2 Integrations
- [ ] OpenClaw skill สำหรับจัดการ RouterAI โดยตรง
- [ ] VS Code extension
- [ ] Chrome extension (ใช้ RouterAI กับ ChatGPT web)
- [ ] Mobile app (Flutter/React Native)

### 7.3 Open Source
- [ ] Contributing guide
- [ ] Code of conduct
- [ ] Issue templates
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Automated testing

---

## 🔧 Technical Debt (สิ่งที่ต้อง refactor)

### Code Quality
- [ ] เพิ่ม type hints ทั้งหมด (Python typing)
- [x] เพิ่ม unit tests (pytest) — 33 tests ✅
- [ ] เพิ่ม integration tests
- [ ] Code formatting (black, isort)
- [ ] Linting (ruff, mypy)
- [ ] Pre-commit hooks

### Config Management
- [ ] ใช้ Pydantic สำหรับ config validation
- [ ] Config schema documentation
- [ ] Hot-reload config (ไม่ต้อง restart)

### Dependencies
- [ ] Pin dependency versions (ตอนนี้ไม่มี version pin)
- [ ] Security audit dependencies

---

## 📊 Priority Matrix

```
                    High Impact
                        │
    ┌───────────────────┼───────────────────┐
    │                   │                   │
    │  Phase 1 (พื้นฐาน) │  Phase 2 (ความปลอดภัย) │
    │  Phase 6 (Production)│  Phase 3 (Smart Routing)│
    │                   │                   │
────┼───────────────────┼───────────────────┼──── High Effort
    │                   │                   │
    │  Phase 7 (Community)│  Phase 4 (Dashboard) │
    │  Phase 5 (Providers)│                   │
    │                   │                   │
    └───────────────────┼───────────────────┘
                        │
                    Low Impact
```

**แนะนำลำดับทำ:**
1. **Phase 1** — แก้ architecture + error handling (ฐานต้องมั่นคง)
2. **Phase 2** — Auth + security (สำคัญมากก่อน public)
3. **Phase 3** — Smart routing (จุดขายหลัก)
4. **Phase 6** — Production readiness
5. **Phase 4** — Dashboard ขั้นสูง
6. **Phase 5** — เพิ่ม providers
7. **Phase 7** — Community

---

## 📝 สำหรับ AI/Developer ที่มาช่วยต่อ

### เริ่มจากตรงไหน?
1. อ่านไฟล์นี้ + `README.md` + `providers.json`
2. รัน `docker compose up -d` แล้วลองใช้
3. เลือก task จาก Phase 1 (ง่ายสุด)
4. สร้าง branch → แก้ → PR

### โครงสร้างโปรเจกต์
```
RouterAI/
├── src/
│   └── server.py       ← Unified server (proxy + dashboard + API) — FastAPI
├── web/
│   └── index.html      ← Dashboard UI (vanilla JS, Thai)
├── tests/
│   └── test_core.py    ← Unit tests
├── scripts/            ← Install & setup scripts
├── .github/
│   └── workflows/
│       └── ci.yml      ← GitHub Actions CI
├── providers.json      ← Provider config (เพิ่ม/ลด ได้)
├── docker-compose.yml  ← Docker deployment
├── Dockerfile          ← Docker image
├── .env.example        ← Environment template
├── requirements.txt    ← Python deps
├── README.md           ← User documentation
└── ROADMAP.md          ← ไฟล์นี้ — development plan
```

### Key Design Decisions
- **FastAPI** — async, เร็ว, auto OpenAPI docs (`/docs`)
- **SQLite** — lightweight, embedded, scalable กว่า file-based JSON
- **Vanilla JS** — ไม่ต้อง build step แต่โค้ดยาว
- **Port 8900 (proxy) + 8899 (dashboard)** — แยกกันตอนนี้ แต่ควรรวม

---

## 🎯 เป้าหมายระยะยาว

> **"ให้คนไทยทุกคนเข้าถึง AI ได้ฟรี ง่าย และปลอดภัย"**

RouterAI ควรเป็น:
- 🔀 **AI Gateway** — ทางเข้าเดียวสำหรับทุก AI API
- 🇹🇭 **Thai-first** — UI ไทย, เอกสารไทย, ชุมชนไทย
- 🆓 **Free-tier focused** — ใช้ฟรีได้จริงๆ
- 🔒 **Privacy-first** — ข้อมูลไม่ออกนอกเครื่อง
- 🤖 **OpenClaw native** — ทำงานร่วมกับ OpenClaw ได้สมบูรณ์

---

*Last updated: 2026-03-29*
*Author: RouterAI Team + AI Assistant*
