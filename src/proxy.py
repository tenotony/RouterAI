#!/usr/bin/env python3
"""
🔀 RouterAI Proxy — OpenAI-compatible API proxy for OpenClaw
รวม AI ฟรีจากหลายที่มาไว้ที่เดียว สลับอัตโนมัติเมื่อตัวไหนหมดโควต้า
"""
import os
import json
import time
import hashlib
import logging
import threading
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

import httpx
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS

# ── Config ──────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
PROVIDERS_FILE = BASE_DIR / "providers.json"
API_KEYS_FILE = BASE_DIR / "api_keys.json"
PROXY_CONFIG_FILE = BASE_DIR / "proxy_config.json"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
STATS_FILE = DATA_DIR / "stats.json"

LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("routerai")

# ── Load providers ──────────────────────────────────
def load_providers():
    try:
        with open(PROVIDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.error(f"Failed to load providers.json: {e}")
        return {}

def load_api_keys():
    if API_KEYS_FILE.exists():
        try:
            with open(API_KEYS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse api_keys.json: {e}")
    return {}

def load_proxy_config():
    if PROXY_CONFIG_FILE.exists():
        try:
            with open(PROXY_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse proxy_config.json: {e}")
    return {
        "prefer_free": True,
        "auto_failover": True,
        "cache_enabled": True,
        "cache_ttl": 3600,
        "budget_daily_usd": 0,
        "budget_action": "downgrade",
        "max_retries": 3,
        "timeout": 60
    }

# ── Stats ───────────────────────────────────────────
class Stats:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self._cleanup_old()

    def _load(self):
        if STATS_FILE.exists():
            try:
                with open(STATS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"requests": [], "daily_cost": {}, "provider_health": {}}

    def _save(self):
        with open(STATS_FILE, "w") as f:
            json.dump(self.data, f, indent=2)

    def _cleanup_old(self):
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        self.data["requests"] = [
            r for r in self.data.get("requests", [])
            if r.get("time", "") > cutoff
        ]
        self._save()

    def record(self, provider, model, tokens_in, tokens_out, latency_ms, success, error=None):
        entry = {
            "time": datetime.now().isoformat(),
            "provider": provider,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
            "success": success,
            "error": error
        }
        self.data.setdefault("requests", []).append(entry)

        # Update provider health
        health = self.data["provider_health"].setdefault(provider, {
            "success": 0, "fail": 0, "last_error": None, "last_check": None
        })
        if success:
            health["success"] += 1
        else:
            health["fail"] += 1
            health["last_error"] = error
        health["last_check"] = datetime.now().isoformat()

        # Daily cost tracking
        today = datetime.now().strftime("%Y-%m-%d")
        daily = self.data["daily_cost"].setdefault(today, {"total": 0, "by_provider": {}})
        daily["by_provider"].setdefault(provider, 0)

        self._save()

    def get_summary(self, days=7):
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        recent = [r for r in self.data.get("requests", []) if r.get("time", "") > cutoff]

        total = len(recent)
        success = sum(1 for r in recent if r.get("success"))
        total_tokens_in = sum(r.get("tokens_in", 0) for r in recent)
        total_tokens_out = sum(r.get("tokens_out", 0) for r in recent)
        avg_latency = (
            sum(r.get("latency_ms", 0) for r in recent) / total
            if total > 0 else 0
        )

        by_provider = defaultdict(lambda: {"count": 0, "success": 0, "tokens": 0, "avg_latency": 0})
        for r in recent:
            p = r.get("provider", "unknown")
            by_provider[p]["count"] += 1
            if r.get("success"):
                by_provider[p]["success"] += 1
            by_provider[p]["tokens"] += r.get("tokens_in", 0) + r.get("tokens_out", 0)

        return {
            "total_requests": total,
            "success_rate": round(success / total * 100, 1) if total else 0,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "avg_latency_ms": round(avg_latency),
            "by_provider": dict(by_provider),
            "daily_cost": self.data.get("daily_cost", {}),
            "provider_health": self.data.get("provider_health", {})
        }

# ── Provider Manager ────────────────────────────────
class ProviderManager:
    def __init__(self):
        self.providers = load_providers()
        self.api_keys = load_api_keys()
        self.config = load_proxy_config()
        self.stats = Stats()
        self._error_counts = defaultdict(int)
        self._last_error_time = defaultdict(float)
        self._reload_keys_from_env()

    def _reload_keys_from_env(self):
        """Load API keys from environment variables"""
        for pid, provider in self.providers.items():
            env_key = provider.get("api_key_env")
            if env_key and env_key not in self.api_keys:
                val = os.environ.get(env_key)
                if val:
                    self.api_keys[env_key] = val

    def get_available_providers(self, model_filter=None):
        """Get list of available providers sorted by priority"""
        self._reload_keys_from_env()
        available = []

        for pid, provider in self.providers.items():
            # Check if we have an API key (except Ollama)
            env_key = provider.get("api_key_env")
            if env_key and not self.api_keys.get(env_key):
                if not os.environ.get(env_key):
                    continue

            # Check error cooldown (5 min cooldown after 3 consecutive errors)
            if self._error_counts[pid] >= 3:
                if time.time() - self._last_error_time[pid] < 300:
                    continue
                else:
                    self._error_counts[pid] = 0

            models = provider.get("models", [])
            if model_filter:
                models = [m for m in models if model_filter in m["id"]]

            if models:
                available.append({
                    "id": pid,
                    "name": provider["name"],
                    "api_base": provider["api_base"],
                    "models": models,
                    "speed": provider.get("speed", ""),
                    "signup_url": provider.get("signup_url", "")
                })

        # Sort by highest model priority
        available.sort(
            key=lambda p: max((m.get("priority", 0) for m in p["models"]), default=0),
            reverse=True
        )
        return available

    def get_api_key(self, provider_id):
        """Get API key for a provider"""
        provider = self.providers.get(provider_id, {})
        env_key = provider.get("api_key_env")
        if not env_key:
            return "ollama"
        key = self.api_keys.get(env_key) or os.environ.get(env_key)
        return key

    def resolve_model(self, requested_model):
        """Find the best provider+model for a given model string"""
        if "/" in requested_model:
            provider_hint, model_id = requested_model.split("/", 1)
        else:
            provider_hint = None
            model_id = requested_model

        available = self.get_available_providers()

        # If specific provider requested, try it first
        if provider_hint:
            for p in available:
                if p["id"] == provider_hint:
                    for m in p["models"]:
                        if model_id in m["id"] or m["id"].endswith(model_id):
                            return p, m
                    if p["models"]:
                        return p, p["models"][0]

        # Auto-select: find best match across all providers
        for p in available:
            for m in p["models"]:
                if model_id == m["id"] or m["id"].endswith(model_id):
                    return p, m

        # Fallback: use highest priority provider + its best model
        if available:
            p = available[0]
            return p, p["models"][0]

        return None, None

    def report_error(self, provider_id, error):
        """Report an error for a provider"""
        self._error_counts[provider_id] += 1
        self._last_error_time[provider_id] = time.time()
        log.warning(f"Provider {provider_id} error #{self._error_counts[provider_id]}: {error}")

    def report_success(self, provider_id):
        """Reset error count on success"""
        self._error_counts[provider_id] = 0

    def save_api_keys(self, keys):
        """Save API keys to file"""
        self.api_keys.update(keys)
        with open(API_KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.api_keys, f, indent=2)

    def reload(self):
        """Reload all configs"""
        self.providers = load_providers()
        self.api_keys = load_api_keys()
        self.config = load_proxy_config()
        self._reload_keys_from_env()

# ── Response Cache ──────────────────────────────────
class ResponseCache:
    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._enabled = True
        self._ttl = 3600

    def update_config(self, enabled, ttl):
        """Update cache settings in memory (call on config reload)"""
        self._enabled = enabled
        self._ttl = ttl

    def _key(self, messages, model):
        content = json.dumps({"messages": messages, "model": model}, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, messages, model):
        if not self._enabled:
            return None
        key = self._key(messages, model)
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            age = time.time() - path.stat().st_mtime
            if age < self._ttl:
                try:
                    with open(path, "r") as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass
        return None

    def set(self, messages, model, response):
        key = self._key(messages, model)
        path = CACHE_DIR / f"{key}.json"
        with open(path, "w") as f:
            json.dump(response, f)

# ── Flask App ───────────────────────────────────────
app = Flask(__name__)
CORS(app)

manager = ProviderManager()
cache = ResponseCache()

# Initialize cache config from loaded config
_cache_cfg = manager.config
cache.update_config(
    _cache_cfg.get("cache_enabled", True),
    _cache_cfg.get("cache_ttl", 3600)
)

# ── API Key Authentication ──────────────────────────
ROUTERAI_API_KEY = os.environ.get("ROUTERAI_API_KEY", "")


def _check_auth():
    """Verify API key if ROUTERAI_API_KEY is set.
    Skip auth for health check and when no key is configured."""
    if not ROUTERAI_API_KEY:
        return True  # No auth configured — open access
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        if token == ROUTERAI_API_KEY:
            return True
    # Also accept via query param ?key= for OpenAI clients
    if request.args.get("key") == ROUTERAI_API_KEY:
        return True
    return False


@app.before_request
def require_auth():
    """Global auth check — skip for health & static"""
    # Allow health check without auth
    if request.path == "/health":
        return None
    # Allow dashboard static files and API without auth (dashboard runs locally)
    if request.path.startswith("/api/") or request.path == "/" or not request.path.startswith("/v1/"):
        return None
    # For /v1/* endpoints, require auth if configured
    if not _check_auth():
        return jsonify({
            "error": {
                "message": "Invalid or missing API key. Set ROUTERAI_API_KEY env var and pass it as Bearer token.",
                "type": "authentication_error",
                "code": "invalid_api_key"
            }
        }), 401


# ── OpenAI-Compatible Endpoints ─────────────────────
@app.route("/v1/models", methods=["GET"])
def list_models():
    """OpenAI-compatible model list"""
    available = manager.get_available_providers()
    models = []
    for p in available:
        for m in p["models"]:
            models.append({
                "id": f"{p['id']}/{m['id']}",
                "object": "model",
                "created": int(time.time()),
                "owned_by": p["name"],
                "free": m.get("free", False),
                "context_length": m.get("context", 0)
            })
    return jsonify({"object": "list", "data": models})


@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    """OpenAI-compatible chat completions with auto-failover"""
    if not request.is_json:
        return jsonify({
            "error": {
                "message": "Request must be JSON with Content-Type: application/json",
                "type": "invalid_request_error",
                "code": "invalid_content_type"
            }
        }), 400

    body = request.json
    if not body:
        return jsonify({
            "error": {
                "message": "Request body is empty",
                "type": "invalid_request_error",
                "code": "empty_body"
            }
        }), 400

    messages = body.get("messages", [])
    if not messages:
        return jsonify({
            "error": {
                "message": "Missing required field: messages",
                "type": "invalid_request_error",
                "code": "missing_messages"
            }
        }), 400

    requested_model = body.get("model", "llama-3.3-70b-versatile")
    stream = body.get("stream", False)

    # Check cache first
    cached = cache.get(messages, requested_model)
    if cached:
        log.info(f"Cache hit for model={requested_model}")
        if stream:
            return Response(
                stream_with_context(_stream_from_cache(cached)),
                content_type="text/event-stream"
            )
        return jsonify(cached)

    # Try providers with failover
    tried = set()
    max_retries = manager.config.get("max_retries", 3)

    for attempt in range(max_retries):
        provider, model = manager.resolve_model(requested_model)
        if not provider or not model:
            return jsonify({
                "error": {
                    "message": "ไม่พบ provider ที่ใช้งานได้ — กรุณาใส่ API Key อย่างน้อย 1 ตัว",
                    "type": "no_provider",
                    "code": "no_available_provider"
                }
            }), 503

        if provider["id"] in tried:
            available = manager.get_available_providers()
            for p in available:
                if p["id"] not in tried:
                    provider, model = p, p["models"][0]
                    break
            else:
                break

        tried.add(provider["id"])
        api_key = manager.get_api_key(provider["id"])

        try:
            start_time = time.time()

            if stream:
                return Response(
                    stream_with_context(_stream_request(provider, model, body, api_key, messages, requested_model)),
                    content_type="text/event-stream"
                )

            result = _make_request(provider, model, body, api_key)
            latency = int((time.time() - start_time) * 1000)

            if "error" in result:
                raise Exception(result.get("error", {}).get("message", "Unknown error"))

            # Record success
            manager.report_success(provider["id"])
            usage = result.get("usage", {})
            manager.stats.record(
                provider["id"], model["id"],
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                latency, True
            )

            # Cache the response
            cache.set(messages, requested_model, result)

            return jsonify(result)

        except Exception as e:
            log.warning(f"Provider {provider['id']} failed: {e}")
            manager.report_error(provider["id"])
            manager.stats.record(
                provider["id"], model.get("id", "?"),
                0, 0, 0, False, str(e)
            )

    return jsonify({
        "error": {
            "message": f"ทุก provider ล้มเหลวหลังจากลอง {len(tried)} ตัว",
            "type": "all_providers_failed",
            "code": "provider_exhausted"
        }
    }), 503


def _make_request(provider, model, body, api_key):
    """Make a non-streaming request to a provider"""
    url = f"{provider['api_base']}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "ollama":
        headers["Authorization"] = f"Bearer {api_key}"

    # Strip proxy-specific fields before forwarding
    payload = {k: v for k, v in body.items() if k != "stream"}
    payload["model"] = model["id"]
    payload["stream"] = False

    timeout = manager.config.get("timeout", 60)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _stream_request(provider, model, body, api_key, messages, requested_model):
    """Stream a request to a provider"""
    url = f"{provider['api_base']}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "ollama":
        headers["Authorization"] = f"Bearer {api_key}"

    # Strip proxy-specific fields before forwarding
    payload = {k: v for k, v in body.items() if k != "stream"}
    payload["model"] = model["id"]
    payload["stream"] = True

    start_time = time.time()
    full_response = ""

    try:
        with httpx.Client(timeout=120) as client:
            with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            yield "data: [DONE]\n\n"
                            break
                        try:
                            chunk = json.loads(data)
                            if chunk.get("choices"):
                                delta = chunk["choices"][0].get("delta", {})
                                full_response += delta.get("content", "")
                            yield f"data: {data}\n\n"
                        except json.JSONDecodeError:
                            continue

        latency = int((time.time() - start_time) * 1000)
        manager.report_success(provider["id"])
        manager.stats.record(provider["id"], model["id"], 0, len(full_response), latency, True)

    except Exception as e:
        log.warning(f"Stream error from {provider['id']}: {e}")
        manager.report_error(provider["id"])
        manager.stats.record(provider["id"], model["id"], 0, 0, 0, False, str(e))
        error_chunk = {
            "error": {
                "message": str(e),
                "type": "stream_error"
            }
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"


def _stream_from_cache(cached):
    """Convert cached response to SSE stream (non-blocking chunked)"""
    choices = cached.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")
        # Send full content in small character chunks without sleep
        # Flask + gevent/gunicorn handles flushing properly
        chunk_size = max(1, len(content) // 50)  # ~50 chunks
        for i in range(0, len(content), chunk_size):
            piece = content[i:i + chunk_size]
            chunk = {
                "choices": [{
                    "delta": {"content": piece},
                    "index": 0
                }]
            }
            yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


# ── Dashboard API ───────────────────────────────────
@app.route("/api/status", methods=["GET"])
def api_status():
    """Overall system status"""
    available = manager.get_available_providers()
    summary = manager.stats.get_summary(days=7)

    return jsonify({
        "status": "running",
        "providers_total": len(manager.providers),
        "providers_available": len(available),
        "config": manager.config,
        "stats": summary
    })


@app.route("/api/providers", methods=["GET"])
def api_providers():
    """List all providers with status"""
    manager.reload()
    # Update cache config on reload
    cache.update_config(
        manager.config.get("cache_enabled", True),
        manager.config.get("cache_ttl", 3600)
    )
    available_ids = {p["id"] for p in manager.get_available_providers()}
    result = []

    for pid, provider in manager.providers.items():
        env_key = provider.get("api_key_env")
        has_key = bool(
            (env_key and manager.api_keys.get(env_key)) or
            (env_key and os.environ.get(env_key)) or
            not env_key  # Ollama
        )

        health = manager.stats.data.get("provider_health", {}).get(pid, {})
        error_count = manager._error_counts.get(pid, 0)

        result.append({
            "id": pid,
            "name": provider["name"],
            "available": pid in available_ids,
            "has_key": has_key,
            "speed": provider.get("speed", ""),
            "models": provider.get("models", []),
            "signup_url": provider.get("signup_url", ""),
            "health": {
                "success": health.get("success", 0),
                "fail": health.get("fail", 0),
                "error_count": error_count,
                "last_error": health.get("last_error"),
                "last_check": health.get("last_check")
            }
        })

    return jsonify({"providers": result})


@app.route("/api/keys", methods=["POST"])
def api_save_keys():
    """Save API keys"""
    data = request.json or {}
    manager.save_api_keys(data)
    manager.reload()
    return jsonify({"status": "ok", "message": "บันทึก API Key เรียบร้อย"})


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    """Get or update proxy config"""
    if request.method == "POST":
        data = request.json or {}
        current = load_proxy_config()
        current.update(data)
        with open(PROXY_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
        manager.reload()
        cache.update_config(
            manager.config.get("cache_enabled", True),
            manager.config.get("cache_ttl", 3600)
        )
        return jsonify({"status": "ok", "message": "บันทึกการตั้งค่าเรียบร้อย"})
    return jsonify(load_proxy_config())


@app.route("/api/openclaw-config", methods=["POST"])
def api_openclaw_config():
    """Generate OpenClaw config snippet"""
    data = request.json or {}
    provider_id = data.get("provider", "groq")
    model_id = data.get("model", "llama-3.3-70b-versatile")

    config = {
        "llm": {
            "provider": "openai",
            "baseUrl": f"http://127.0.0.1:{os.environ.get('ROUTERAI_PORT', '8900')}/v1",
            "apiKey": "routerai",
            "model": f"{provider_id}/{model_id}"
        }
    }

    return jsonify({
        "config": config,
        "instructions": "คัดลอก config นี้ไปวางใน ~/.openclaw/openclaw.json แล้วรัน openclaw restart"
    })


@app.route("/api/stats", methods=["GET"])
def api_stats():
    """Get usage statistics"""
    days = int(request.args.get("days", 7))
    return jsonify(manager.stats.get_summary(days=days))


@app.route("/api/test/<provider_id>", methods=["POST"])
def api_test_provider(provider_id):
    """Test a specific provider"""
    provider = manager.providers.get(provider_id)
    if not provider:
        return jsonify({"error": "ไม่พบ provider"}), 404

    api_key = manager.get_api_key(provider_id)
    if not api_key:
        return jsonify({"error": "ไม่พบ API Key"}), 400

    model = provider["models"][0]
    try:
        start = time.time()
        result = _make_request(provider, model, {
            "messages": [{"role": "user", "content": "สวัสดี ตอบสั้นๆ ว่าใช้งานได้"}],
            "max_tokens": 50
        }, api_key)
        latency = int((time.time() - start) * 1000)

        if "error" in result:
            return jsonify({"success": False, "error": result["error"], "latency_ms": latency})

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        return jsonify({"success": True, "response": content, "latency_ms": latency, "model": model["id"]})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Health Check ────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


# ── Main ────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("ROUTERAI_PORT", 8900))
    host = os.environ.get("ROUTERAI_HOST", "127.0.0.1")

    print(f"""
╔══════════════════════════════════════════╗
║  🔀 RouterAI Proxy — OpenAI-compatible  ║
║  🌐 http://{host}:{port}                ║
║  📊 Dashboard: http://127.0.0.1:8899    ║
╚══════════════════════════════════════════╝
    """)

    app.run(host=host, port=port, debug=False)
