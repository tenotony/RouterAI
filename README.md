# 🔀 RouterAI — รวม AI ฟรีสำหรับ OpenClaw

รวม AI ฟรีจากหลายที่มาไว้ที่เดียว สลับอัตโนมัติเมื่อตัวไหนหมดโควต้า

**OpenAI-compatible API proxy** ใช้แทน OpenAI endpoint ได้เลย สำหรับ OpenClaw, ChatGPT-like apps, หรือโปรแกรมอะไรก็ได้ที่รองรับ OpenAI API

![Dashboard](docs/dashboard-preview.png)

## ✨ ฟีเจอร์

- 🔄 **Auto-Failover** — สลับ Provider อัตโนมัติเมื่อตัวไหน Error/หมดโควต้า
- 🇹🇭 **UI ภาษาไทย** — หน้าตาเข้าใจง่าย ใช้ได้ทันที
- 🔒 **ปลอดภัย** — รันบนเครื่องคุณ ไม่ส่งข้อมูลให้ใคร
- 💰 **ประหยัดเงิน** — ใช้ของฟรีก่อน หมดโควต้าค่อยสลับ
- 📦 **ติดตั้งง่าย** — บรรทัดเดียวจบ
- 🤖 **OpenClaw Ready** — ตั้งค่า OpenClaw ได้จาก Dashboard เลย
- ⚡ **Response Cache** — จำคำตอบเดิม ไม่เสีย Token ซ้ำ

## 🚀 ติดตั้ง (บรรทัดเดียว)

```bash
curl -fsSL https://raw.githubusercontent.com/tenotony/RouterAI/main/scripts/install.sh | bash
```

### ด้วย Docker (แนะนำ)

```bash
git clone https://github.com/tenotony/RouterAI.git
cd RouterAI
docker compose up -d
```

### ด้วยมือ (ไม่ต้องใช้ Docker)

```bash
git clone https://github.com/tenotony/RouterAI.git
cd RouterAI
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Terminal 1: รัน Proxy
python src/proxy.py

# Terminal 2: รัน Dashboard
python src/dashboard.py
```

## 📊 Dashboard

เปิด [http://localhost:8899](http://localhost:8899) หลังติดตั้งเสร็จ:

| หน้า | ทำอะไร |
|------|--------|
| 📊 แดชบอร์ด | ดูสถานะทุก Provider |
| 🔌 ผู้ให้บริการ | ดูรายละเอียด + ทดสอบ |
| 🔑 จัดการ API Key | กรอก Key สำหรับแต่ละเจ้า |
| 🤖 เชื่อม OpenClaw | สร้าง Config อัตโนมัติ |
| ⚙️ ตั้งค่า | ปรับแต่งระบบ |
| 📦 คู่มือติดตั้ง | วิธีติดตั้งทุกรูปแบบ |
| 🩺 ตรวจสอบระบบ | ตรวจสอบสุขภาพระบบ |

## 🤖 ตั้งค่า OpenClaw

1. ใส่ API Key อย่างน้อย 1 ตัว (แนะนำ Groq)
2. Dashboard → หน้า "เชื่อม OpenClaw" → เลือก Provider + Model → กดปุ่ม ⚡
3. คัดลอก config ไปวางใน `~/.openclaw/openclaw.json`
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

## 🔑 แหล่ง API Key ฟรี

| Provider | ลิงก์สมัคร | ทำไมต้องสมัคร | ความเร็ว |
|----------|-----------|--------------|---------|
| ⚡ Groq | [console.groq.com/keys](https://console.groq.com/keys) | เร็วสุดๆ ~300ms | ⭐⭐⭐⭐⭐ |
| 🚀 Cerebras | [cloud.cerebras.ai](https://cloud.cerebras.ai) | เร็วมาก | ⭐⭐⭐⭐⭐ |
| 🟢 Google Gemini | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | ฟรี 15 RPM, vision | ⭐⭐⭐⭐ |
| 🌐 OpenRouter | [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) | โมเดลฟรีเยอะ | ⭐⭐⭐ |
| 🟣 Mistral | [console.mistral.ai](https://console.mistral.ai/api-keys/) | Mistral models | ⭐⭐⭐ |
| 🔵 NVIDIA | [build.nvidia.com](https://build.nvidia.com/explore/discover) | Llama ฟรี | ⭐⭐⭐ |
| 💎 DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) | คุณภาพสูง | ⭐⭐⭐⭐ |
| 🇨🇳 SiliconFlow | [cloud.siliconflow.cn](https://cloud.siliconflow.cn) | Qwen ฟรี | ⭐⭐⭐ |
| 🤝 Together AI | [api.together.xyz](https://api.together.xyz/settings/api-keys) | $5 เครดิตฟรี | ⭐⭐⭐ |
| 🏠 Ollama | [ollama.com](https://ollama.com) | รัน Local ฟรี | ⭐⭐⭐⭐ |

💡 **แนะนำ:** สมัครแค่ Groq ตัวเดียวก็เริ่มใช้ได้เลย!

## 🔄 อัพเดต

```bash
cd RouterAI
bash scripts/update.sh
```

สคริปต์จะ:
- ✅ สำรอง config/API Key ของคุณ
- ✅ ดึงโค้ดล่าสุด
- ✅ กู้คืน config กลับ
- ✅ Rebuild Docker
- ✅ Restart ทุกอย่าง

## 🏗️ โครงสร้างโปรเจค

```
RouterAI/
├── src/
│   ├── proxy.py          # Main proxy server (OpenAI-compatible)
│   └── dashboard.py      # Web dashboard server
├── web/
│   └── index.html        # Dashboard UI (ภาษาไทย)
├── scripts/
│   ├── install.sh        # One-line installer
│   └── update.sh         # Update script
├── docker-compose.yml    # Docker Compose config
├── Dockerfile            # Proxy container
├── Dockerfile.dashboard  # Dashboard container
├── .env.example          # Environment template
├── providers.json        # Provider config
├── requirements.txt      # Python dependencies
└── README.md             # This file
```

## 🔒 ความปลอดภัย

- ✅ รันบนเครื่องคุณ ไม่ส่งข้อมูลให้ใคร
- ✅ API Key เก็บในเครื่องเท่านั้น
- ✅ ไม่มี tracking / analytics
- ✅ Open source — ตรวจสอบได้ทุกบรรทัด

## 📝 License

MIT License
