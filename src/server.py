#!/usr/bin/env python3
"""
🔀 RouterAI — Unified Server (Proxy + Dashboard)
OpenAI-compatible API proxy with web dashboard, auto-failover, rate limiting, and smart routing.

Single server on one port:
  /v1/*       → OpenAI-compatible proxy endpoints
  /api/*      → Dashboard API
  /           → Dashboard UI (static files)
  /health     → Health check
"""
import os
import sys
import json
import time
import hashlib
import logging
import threading
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

import httpx
from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory
from flask_cors import CORS

# ── Config ──────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
PROVIDERS_FILE = BASE_DIR / "providers.json"
API_KEYS_FILE = BASE_DIR / "api_keys.json"
PROXY_CONFIG_FILE = BASE_DIR / "proxy_config.json"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
STATS_FILE = DATA_DIR / "stats.json"
WEB_DIR = BASE_DIR / "web"

LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("routerai")


# ── Load Config Helpers ─────────────────────────────
def load_json_file(path: Path, default=None):
    """Safely load a JSON file with fallback."""
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.error(f"Failed to load {path}: {e}")
    return default or {}


def load_providers():
    return load_json_file(PROVIDERS_FILE, {})


def load_api_keys():
    return load_json_file(API_KEYS_FILE, {})


def load_proxy_config():
    defaults = {
        "prefer_free": True,
        "auto_failover": True,
        "cache_enabled": True,
        "cache_ttl": 3600,
        "budget_daily_usd": 0,
        "budget_action": "downgrade",
        "max_retries": 3,
        "timeout": 60,
        "rate_limit_rpm": 0,  # 0 = unlimited
    }
    cfg = load_json_file(PROXY_CONFIG_FILE, {})
    defaults.update(cfg)
    return defaults


def save_json_file(path: Path, data):
    """Write JSON to file with proper encoding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Rate Limiter ────────────────────────────────────
class RateLimiter:
    """Token-bucket rate limiter per client IP."""

    def __init__(self):
        self._buckets = {}
        self._lock = threading.Lock()
        self._rpm = 0  # 0 = disabled

    def configure(self, rpm: int):
        self._rpm = rpm
        self._buckets.clear()  # Reset on reconfigure

    def _get_bucket(self, client_ip: str):
        if client_ip not in self._buckets:
            self._buckets[client_ip] = {
                "tokens": self._rpm,  # Start full
                "last_refill": time.time()
            }
        return self._buckets[client_ip]

    def is_allowed(self, client_ip: str) -> bool:
        if self._rpm <= 0:
            return True

        with self._lock:
            bucket = self._get_bucket(client_ip)
            now = time.time()
            elapsed = now - bucket["last_refill"]

            # Refill tokens
            refill_rate = self._rpm / 60.0
            bucket["tokens"] = min(self._rpm, bucket["tokens"] + elapsed * refill_rate)
            bucket["last_refill"] = now

            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True
            return False

    def get_wait_time(self, client_ip: str) -> float:
        """Return seconds until next request is allowed."""
        if self._rpm <= 0:
            return 0
        bucket = self._buckets.get(client_ip)
        if not bucket or bucket["tokens"] >= 1:
            return 0
        refill_rate = self._rpm / 60.0
        deficit = 1 - bucket["tokens"]
        return deficit / refill_rate if refill_rate > 0 else 1


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
        save_json_file(STATS_FILE, self.data)

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

        health = self.data["provider_health"].setdefault(provider, {
            "success": 0, "fail": 0, "last_error": None, "last_check": None
        })
        if success:
            health["success"] += 1
        else:
            health["fail"] += 1
            health["last_error"] = error
        health["last_check"] = datetime.now().isoformat()

        today = datetime.now().strftime("%Y-%m-%d")
        daily = self.data["daily_cost"].setdefault(today, {"total": 0, "by_provider": {}})
        daily["by_provider"].setdefault(provider, 0)

        # Batch saves: only save every 10 records to reduce I/O
        if len(self.data["requests"]) % 10 == 0:
            self._save()

    def flush(self):
        """Force save to disk."""
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
        self._cooldown_until = defaultdict(float)
        self._reload_keys_from_env()

    def _reload_keys_from_env(self):
        for pid, provider in self.providers.items():
            env_key = provider.get("api_key_env")
            if env_key and env_key not in self.api_keys:
                val = os.environ.get(env_key)
                if val:
                    self.api_keys[env_key] = val

    def get_available_providers(self, model_filter=None):
        self._reload_keys_from_env()
        available = []

        for pid, provider in self.providers.items():
            env_key = provider.get("api_key_env")
            if env_key and not self.api_keys.get(env_key):
                if not os.environ.get(env_key):
                    continue

            # Cooldown check with exponential backoff
            if time.time() < self._cooldown_until[pid]:
                continue

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

        available.sort(
            key=lambda p: max((m.get("priority", 0) for m in p["models"]), default=0),
            reverse=True
        )
        return available

    def get_api_key(self, provider_id):
        provider = self.providers.get(provider_id, {})
        env_key = provider.get("api_key_env")
        if not env_key:
            return "ollama"
        return self.api_keys.get(env_key) or os.environ.get(env_key)

    def resolve_model(self, requested_model):
        if "/" in requested_model:
            provider_hint, model_id = requested_model.split("/", 1)
        else:
            provider_hint = None
            model_id = requested_model

        available = self.get_available_providers()

        if provider_hint:
            for p in available:
                if p["id"] == provider_hint:
                    for m in p["models"]:
                        if model_id in m["id"] or m["id"].endswith(model_id):
                            return p, m
                    if p["models"]:
                        return p, p["models"][0]

        for p in available:
            for m in p["models"]:
                if model_id == m["id"] or m["id"].endswith(model_id):
                    return p, m

        if available:
            p = available[0]
            return p, p["models"][0]

        return None, None

    def report_error(self, provider_id, error):
        """Report error with exponential backoff: 30s → 60s → 120s → 300s (max 5min)"""
        self._error_counts[provider_id] += 1
        self._last_error_time[provider_id] = time.time()

        count = self._error_counts[provider_id]
        if count >= 3:
            # Exponential backoff: 30 * 2^(count-3), max 300s
            cooldown = min(30 * (2 ** (count - 3)), 300)
            self._cooldown_until[provider_id] = time.time() + cooldown
            log.warning(
                f"Provider {provider_id} cooldown {cooldown}s "
                f"(error #{count}): {error}"
            )
        else:
            log.warning(f"Provider {provider_id} error #{count}: {error}")

    def report_success(self, provider_id):
        self._error_counts[provider_id] = 0
        self._cooldown_until[provider_id] = 0

    def save_api_keys(self, keys):
        self.api_keys.update(keys)
        save_json_file(API_KEYS_FILE, self.api_keys)

    def reload(self):
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
        save_json_file(path, response)

    def clear(self):
        """Clear all cached responses."""
        for f in CACHE_DIR.glob("*.json"):
            f.unlink(missing_ok=True)

    def get_stats(self):
        """Return cache statistics."""
        files = list(CACHE_DIR.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "entries": len(files),
            "total_size_kb": round(total_size / 1024, 1),
            "enabled": self._enabled,
            "ttl_seconds": self._ttl
        }


# ── HTTP Client Pool ────────────────────────────────
_http_client = None
_http_client_lock = threading.Lock()


def get_http_client(timeout=60):
    """Get a shared HTTP client with connection pooling."""
    global _http_client
    with _http_client_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = httpx.Client(
                timeout=timeout,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                http2=True,
            )
        return _http_client


# ── Flask App ───────────────────────────────────────
app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
CORS(app)

manager = ProviderManager()
cache = ResponseCache()
rate_limiter = RateLimiter()

# Initialize cache config
cache.update_config(
    manager.config.get("cache_enabled", True),
    manager.config.get("cache_ttl", 3600)
)
rate_limiter.configure(manager.config.get("rate_limit_rpm", 0))

# ── API Key Authentication ──────────────────────────
ROUTERAI_API_KEY = os.environ.get("ROUTERAI_API_KEY", "")


def _check_auth():
    if not ROUTERAI_API_KEY:
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == ROUTERAI_API_KEY:
        return True
    if request.args.get("key") == ROUTERAI_API_KEY:
        return True
    return False


@app.before_request
def global_checks():
    """Global auth + rate limit checks."""
    # Skip for health check and static files
    if request.path == "/health" or request.path.startswith("/static"):
        return None

    # Skip for dashboard UI and dashboard API (local access)
    if (request.path == "/" or
            request.path.startswith("/api/") or
            not request.path.startswith("/v1/")):
        # Still apply rate limit to API endpoints
        if request.path.startswith("/api/"):
            client_ip = request.remote_addr or "unknown"
            if not rate_limiter.is_allowed(client_ip):
                wait = rate_limiter.get_wait_time(client_ip)
                return jsonify({
                    "error": {
                        "message": f"Rate limit exceeded. Try again in {wait:.1f}s",
                        "type": "rate_limit_error",
                        "retry_after": round(wait, 1)
                    }
                }), 429
        return None

    # For /v1/* endpoints: auth + rate limit
    if not _check_auth():
        return jsonify({
            "error": {
                "message": "Invalid or missing API key. Set ROUTERAI_API_KEY env var.",
                "type": "authentication_error",
                "code": "invalid_api_key"
            }
        }), 401

    client_ip = request.remote_addr or "unknown"
    if not rate_limiter.is_allowed(client_ip):
        wait = rate_limiter.get_wait_time(client_ip)
        return jsonify({
            "error": {
                "message": f"Rate limit exceeded. Try again in {wait:.1f}s",
                "type": "rate_limit_error",
                "retry_after": round(wait, 1)
            }
        }), 429

    return None


# ══════════════════════════════════════════════════════
#  OpenAI-Compatible Proxy Endpoints
# ══════════════════════════════════════════════════════

@app.route("/v1/models", methods=["GET"])
def list_models():
    """OpenAI-compatible model list."""
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
    """OpenAI-compatible chat completions with auto-failover."""
    if not request.is_json:
        return jsonify({
            "error": {"message": "Request must be JSON", "type": "invalid_request_error"}
        }), 400

    body = request.json
    if not body:
        return jsonify({
            "error": {"message": "Request body is empty", "type": "invalid_request_error"}
        }), 400

    messages = body.get("messages", [])
    if not messages:
        return jsonify({
            "error": {"message": "Missing required field: messages", "type": "invalid_request_error"}
        }), 400

    requested_model = body.get("model", "llama-3.3-70b-versatile")
    stream = body.get("stream", False)

    # Check cache
    cached = cache.get(messages, requested_model)
    if cached:
        log.info(f"Cache hit for model={requested_model}")
        if stream:
            return Response(
                stream_with_context(_stream_from_cache(cached)),
                content_type="text/event-stream"
            )
        return jsonify(cached)

    # Try providers with failover + exponential retry
    tried = set()
    max_retries = manager.config.get("max_retries", 3)
    last_error = None

    for attempt in range(max_retries):
        provider, model = manager.resolve_model(requested_model)
        if not provider or not model:
            break

        # Find an untried provider
        if provider["id"] in tried:
            available = manager.get_available_providers()
            found = False
            for p in available:
                if p["id"] not in tried:
                    provider, model = p, p["models"][0]
                    found = True
                    break
            if not found:
                break

        tried.add(provider["id"])
        api_key = manager.get_api_key(provider["id"])

        try:
            start_time = time.time()

            if stream:
                return Response(
                    stream_with_context(
                        _stream_request(provider, model, body, api_key, messages, requested_model)
                    ),
                    content_type="text/event-stream"
                )

            result = _make_request(provider, model, body, api_key)
            latency = int((time.time() - start_time) * 1000)

            if "error" in result:
                raise Exception(result.get("error", {}).get("message", "Unknown error"))

            # Success
            manager.report_success(provider["id"])
            usage = result.get("usage", {})
            manager.stats.record(
                provider["id"], model["id"],
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                latency, True
            )
            cache.set(messages, requested_model, result)
            return jsonify(result)

        except httpx.HTTPStatusError as e:
            last_error = str(e)
            if e.response.status_code == 429:
                # Rate limited — wait and retry same provider
                retry_after = float(e.response.headers.get("Retry-After", 2))
                log.warning(f"Rate limited by {provider['id']}, waiting {retry_after}s")
                time.sleep(min(retry_after, 5))
                tried.discard(provider["id"])  # Allow retry of same provider
                continue
            manager.report_error(provider["id"], last_error)
            manager.stats.record(provider["id"], model.get("id", "?"), 0, 0, 0, False, last_error)

        except Exception as e:
            last_error = str(e)
            manager.report_error(provider["id"], last_error)
            manager.stats.record(provider["id"], model.get("id", "?"), 0, 0, 0, False, last_error)

    # Force save stats after all retries
    manager.stats.flush()

    return jsonify({
        "error": {
            "message": f"ทุก provider ล้มเหลว ({len(tried)} ตัว): {last_error or 'no providers available'}",
            "type": "all_providers_failed",
            "code": "provider_exhausted"
        }
    }), 503


def _make_request(provider, model, body, api_key):
    """Make a non-streaming request to a provider."""
    url = f"{provider['api_base']}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "ollama":
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {k: v for k, v in body.items() if k not in ("stream",)}
    payload["model"] = model["id"]
    payload["stream"] = False

    timeout = manager.config.get("timeout", 60)
    client = get_http_client(timeout)
    resp = client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()


def _stream_request(provider, model, body, api_key, messages, requested_model):
    """Stream a request to a provider."""
    url = f"{provider['api_base']}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "ollama":
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {k: v for k, v in body.items() if k not in ("stream",)}
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
        manager.report_error(provider["id"], str(e))
        manager.stats.record(provider["id"], model["id"], 0, 0, 0, False, str(e))
        error_chunk = {"error": {"message": str(e), "type": "stream_error"}}
        yield f"data: {json.dumps(error_chunk)}\n\n"


def _stream_from_cache(cached):
    """Convert cached response to SSE stream."""
    choices = cached.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")
        chunk_size = max(1, len(content) // 50)
        for i in range(0, len(content), chunk_size):
            piece = content[i:i + chunk_size]
            chunk = {"choices": [{"delta": {"content": piece}, "index": 0}]}
            yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


# ══════════════════════════════════════════════════════
#  Dashboard UI
# ══════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory(str(WEB_DIR), "index.html")


# ══════════════════════════════════════════════════════
#  Dashboard API
# ══════════════════════════════════════════════════════

@app.route("/api/status", methods=["GET"])
def api_status():
    available = manager.get_available_providers()
    summary = manager.stats.get_summary(days=7)
    return jsonify({
        "status": "running",
        "version": "1.1.0",
        "providers_total": len(manager.providers),
        "providers_available": len(available),
        "config": manager.config,
        "stats": summary,
        "cache": cache.get_stats(),
        "rate_limit_rpm": manager.config.get("rate_limit_rpm", 0)
    })


@app.route("/api/providers", methods=["GET"])
def api_providers():
    manager.reload()
    cache.update_config(
        manager.config.get("cache_enabled", True),
        manager.config.get("cache_ttl", 3600)
    )
    rate_limiter.configure(manager.config.get("rate_limit_rpm", 0))

    available_ids = {p["id"] for p in manager.get_available_providers()}
    result = []

    for pid, provider in manager.providers.items():
        env_key = provider.get("api_key_env")
        has_key = bool(
            (env_key and manager.api_keys.get(env_key)) or
            (env_key and os.environ.get(env_key)) or
            not env_key
        )

        health = manager.stats.data.get("provider_health", {}).get(pid, {})
        error_count = manager._error_counts.get(pid, 0)
        cooldown = manager._cooldown_until.get(pid, 0)

        result.append({
            "id": pid,
            "name": provider["name"],
            "available": pid in available_ids,
            "has_key": has_key,
            "speed": provider.get("speed", ""),
            "models": provider.get("models", []),
            "signup_url": provider.get("signup_url", ""),
            "desc": provider.get("desc", ""),
            "flag": provider.get("flag", "🌐"),
            "health": {
                "success": health.get("success", 0),
                "fail": health.get("fail", 0),
                "error_count": error_count,
                "cooldown_until": cooldown,
                "in_cooldown": time.time() < cooldown,
                "last_error": health.get("last_error"),
                "last_check": health.get("last_check")
            }
        })

    return jsonify({"providers": result})


@app.route("/api/keys", methods=["POST"])
def api_save_keys():
    data = request.json or {}
    manager.save_api_keys(data)
    manager.reload()
    return jsonify({"status": "ok", "message": "บันทึก API Key เรียบร้อย ✅"})


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        data = request.json or {}
        current = load_proxy_config()
        current.update(data)
        save_json_file(PROXY_CONFIG_FILE, current)
        manager.reload()
        cache.update_config(
            manager.config.get("cache_enabled", True),
            manager.config.get("cache_ttl", 3600)
        )
        rate_limiter.configure(manager.config.get("rate_limit_rpm", 0))
        return jsonify({"status": "ok", "message": "บันทึกการตั้งค่าเรียบร้อย ✅"})
    return jsonify(load_proxy_config())


@app.route("/api/cache/clear", methods=["POST"])
def api_cache_clear():
    """Clear all cached responses."""
    cache.clear()
    return jsonify({"status": "ok", "message": "ล้าง cache เรียบร้อย ✅"})


@app.route("/api/cache/stats", methods=["GET"])
def api_cache_stats():
    """Get cache statistics."""
    return jsonify(cache.get_stats())


@app.route("/api/openclaw-config", methods=["POST"])
def api_openclaw_config():
    data = request.json or {}
    provider_id = data.get("provider", "groq")
    model_id = data.get("model", "llama-3.3-70b-versatile")
    port = int(os.environ.get("ROUTERAI_PORT", 8900))

    config = {
        "llm": {
            "provider": "openai",
            "baseUrl": f"http://127.0.0.1:{port}/v1",
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
    days = int(request.args.get("days", 7))
    return jsonify(manager.stats.get_summary(days=days))


@app.route("/api/test/<provider_id>", methods=["POST"])
def api_test_provider(provider_id):
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


@app.route("/api/models/compare", methods=["POST"])
def api_compare_models():
    """Send the same prompt to multiple models and compare."""
    data = request.json or {}
    prompt = data.get("prompt", "Hello, who are you?")
    provider_ids = data.get("providers", [])

    if not provider_ids:
        available = manager.get_available_providers()
        provider_ids = [p["id"] for p in available[:3]]

    results = []
    for pid in provider_ids:
        provider = manager.providers.get(pid)
        if not provider:
            continue
        api_key = manager.get_api_key(pid)
        if not api_key:
            continue
        model = provider["models"][0]
        try:
            start = time.time()
            result = _make_request(provider, model, {
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200
            }, api_key)
            latency = int((time.time() - start) * 1000)
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            results.append({
                "provider": pid,
                "model": model["id"],
                "response": content,
                "latency_ms": latency,
                "success": True
            })
        except Exception as e:
            results.append({
                "provider": pid,
                "model": model.get("id", "?"),
                "error": str(e),
                "success": False
            })

    return jsonify({"results": results})


# ── Health Check ────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    available = manager.get_available_providers()
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "providers_available": len(available),
        "providers_total": len(manager.providers),
        "version": "1.1.0"
    })


# ── Periodic Stats Flush ────────────────────────────
def _periodic_flush():
    """Background thread to periodically flush stats to disk."""
    while True:
        time.sleep(60)
        try:
            manager.stats.flush()
        except Exception as e:
            log.error(f"Stats flush error: {e}")


# ── Main ────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("ROUTERAI_PORT", 8900))
    host = os.environ.get("ROUTERAI_HOST", "127.0.0.1")
    debug = os.environ.get("ROUTERAI_DEBUG", "").lower() in ("1", "true", "yes")

    # Start background stats flusher
    flush_thread = threading.Thread(target=_periodic_flush, daemon=True)
    flush_thread.start()

    print(f"""
╔══════════════════════════════════════════════════╗
║  🔀 RouterAI v1.1.0 — Unified Server           ║
║  🌐 Proxy + Dashboard: http://{host}:{port}      ║
║  📊 API Docs:            http://{host}:{port}/v1/models
╚══════════════════════════════════════════════════╝
    """)

    app.run(host=host, port=port, debug=debug)
