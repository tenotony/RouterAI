#!/usr/bin/env python3
"""
🔀 RouterAI Dashboard — Web UI for managing providers
"""
import os
import json
import logging
from pathlib import Path

from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS

BASE_DIR = Path(__file__).parent.parent
WEB_DIR = BASE_DIR / "web"
API_KEYS_FILE = BASE_DIR / "api_keys.json"
PROVIDERS_FILE = BASE_DIR / "providers.json"
PROXY_CONFIG_FILE = BASE_DIR / "proxy_config.json"

PROXY_URL = os.environ.get("PROXY_URL", "http://127.0.0.1:8900")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", 8899))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("dashboard")

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
CORS(app)

def load_json(path, default=None):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default or {}

# ── Serve Dashboard UI ──────────────────────────────
@app.route("/")
def index():
    return send_from_directory(str(WEB_DIR), "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(str(WEB_DIR), path)

# ── Local Dashboard API (mirrors proxy API + extras) ─
@app.route("/api/providers")
def providers():
    providers_data = load_json(PROVIDERS_FILE, {})
    keys_data = load_json(API_KEYS_FILE, {})
    result = []

    for pid, p in providers_data.items():
        env_key = p.get("api_key_env")
        has_key = bool(
            (env_key and keys_data.get(env_key)) or
            (env_key and os.environ.get(env_key)) or
            not env_key
        )
        result.append({
            "id": pid,
            "name": p.get("name", pid),
            "has_key": has_key,
            "speed": p.get("speed", ""),
            "models": p.get("models", []),
            "signup_url": p.get("signup_url", ""),
            "available": has_key
        })

    return jsonify({"providers": result})

@app.route("/api/keys", methods=["POST"])
def save_keys():
    data = request.json or {}
    # Merge with existing
    existing = load_json(API_KEYS_FILE, {})
    existing.update(data)
    with open(API_KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    return jsonify({"status": "ok", "message": "บันทึก API Key เรียบร้อย"})

@app.route("/api/config", methods=["GET", "POST"])
def config():
    if request.method == "POST":
        data = request.json or {}
        existing = load_json(PROXY_CONFIG_FILE, {})
        existing.update(data)
        with open(PROXY_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        return jsonify({"status": "ok"})
    return jsonify(load_json(PROXY_CONFIG_FILE, {}))

@app.route("/api/openclaw-config", methods=["POST"])
def openclaw_config():
    data = request.json or {}
    provider_id = data.get("provider", "groq")
    model_id = data.get("model", "llama-3.3-70b-versatile")

    config = {
        "llm": {
            "provider": "openai",
            "baseUrl": f"http://127.0.0.1:8900/v1",
            "apiKey": "routerai",
            "model": f"{provider_id}/{model_id}"
        }
    }

    return jsonify({
        "config": config,
        "instructions": "คัดลอก config นี้ไปวางใน ~/.openclaw/openclaw.json แล้วรัน openclaw restart"
    })

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "proxy_url": PROXY_URL})

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════╗
║  🔀 RouterAI Dashboard — แผงควบคุม      ║
║  🌐 http://127.0.0.1:{DASHBOARD_PORT}         ║
╚══════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False)
