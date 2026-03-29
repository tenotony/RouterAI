#!/usr/bin/env python3
"""
🔀 RouterAI — Unified Server (Proxy + Dashboard)
OpenAI-compatible API proxy with web dashboard, auto-failover, rate limiting, and smart routing.

Single server on one port:
  /v1/*       → OpenAI-compatible proxy endpoints
  /api/*      → Dashboard API
  /           → Dashboard UI (static files)
  /health     → Health check

Built with FastAPI + SQLite for production performance.
"""
import os
import sys
import json
import time
import hashlib
import logging
import sqlite3
import threading
import signal
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# ── Config ──────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
PROVIDERS_FILE = BASE_DIR / "providers.json"
API_KEYS_FILE = BASE_DIR / "api_keys.json"
PROXY_CONFIG_FILE = BASE_DIR / "proxy_config.json"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
STATS_DB = DATA_DIR / "stats.db"
WEB_DIR = BASE_DIR / "web"

LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
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


# ── SQLite Stats ────────────────────────────────────
class StatsDB:
    """SQLite-backed statistics — replaces JSON file for performance."""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(STATS_DB), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_tables()
        self._cleanup_old()

    def _init_tables(self):
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    latency_ms INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 1,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts);
                CREATE INDEX IF NOT EXISTS idx_requests_provider ON requests(provider);

                CREATE TABLE IF NOT EXISTS provider_health (
                    provider TEXT PRIMARY KEY,
                    success INTEGER DEFAULT 0,
                    fail INTEGER DEFAULT 0,
                    last_error TEXT,
                    last_check TEXT
                );
            """)
            self._conn.commit()

    def _cleanup_old(self):
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        with self._lock:
            self._conn.execute("DELETE FROM requests WHERE ts < ?", (cutoff,))
            self._conn.commit()

    def record(self, provider, model, tokens_in, tokens_out, latency_ms, success, error=None):
        now = datetime.now().isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO requests (ts, provider, model, tokens_in, tokens_out, latency_ms, success, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now, provider, model, tokens_in, tokens_out, latency_ms, int(success), error),
            )
            # Upsert provider health
            self._conn.execute(
                """
                INSERT INTO provider_health (provider, success, fail, last_error, last_check)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    success = success + excluded.success,
                    fail = fail + excluded.fail,
                    last_error = excluded.last_error,
                    last_check = excluded.last_check
                """,
                (provider, int(success), int(not success), error, now),
            )
            self._conn.commit()

    def get_summary(self, days=7):
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*), SUM(success), SUM(tokens_in), SUM(tokens_out), AVG(latency_ms) "
                "FROM requests WHERE ts > ?",
                (cutoff,),
            )
            row = cur.fetchone()
            total = row[0] or 0
            success_count = row[1] or 0
            total_tokens_in = row[2] or 0
            total_tokens_out = row[3] or 0
            avg_latency = round(row[4] or 0)

            # By provider
            cur = self._conn.execute(
                "SELECT provider, COUNT(*), SUM(success), SUM(tokens_in + tokens_out), AVG(latency_ms) "
                "FROM requests WHERE ts > ? GROUP BY provider",
                (cutoff,),
            )
            by_provider = {}
            for prow in cur.fetchall():
                by_provider[prow[0]] = {
                    "count": prow[1],
                    "success": prow[2] or 0,
                    "tokens": prow[3] or 0,
                    "avg_latency": round(prow[4] or 0),
                }

            # Provider health
            cur = self._conn.execute("SELECT provider, success, fail, last_error, last_check FROM provider_health")
            provider_health = {}
            for hrow in cur.fetchall():
                provider_health[hrow[0]] = {
                    "success": hrow[1],
                    "fail": hrow[2],
                    "last_error": hrow[3],
                    "last_check": hrow[4],
                }

        return {
            "total_requests": total,
            "success_rate": round(success_count / total * 100, 1) if total else 0,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "avg_latency_ms": avg_latency,
            "by_provider": by_provider,
            "provider_health": provider_health,
        }

    def close(self):
        with self._lock:
            self._conn.close()


# ── Rate Limiter ────────────────────────────────────
class RateLimiter:
    """Token-bucket rate limiter per client IP."""

    def __init__(self):
        self._buckets: dict = {}
        self._lock = threading.Lock()
        self._rpm = 0

    def configure(self, rpm: int):
        self._rpm = rpm
        self._buckets.clear()

    def _get_bucket(self, client_ip: str):
        if client_ip not in self._buckets:
            self._buckets[client_ip] = {"tokens": self._rpm, "last_refill": time.time()}
        return self._buckets[client_ip]

    def is_allowed(self, client_ip: str) -> bool:
        if self._rpm <= 0:
            return True
        with self._lock:
            bucket = self._get_bucket(client_ip)
            now = time.time()
            elapsed = now - bucket["last_refill"]
            refill_rate = self._rpm / 60.0
            bucket["tokens"] = min(self._rpm, bucket["tokens"] + elapsed * refill_rate)
            bucket["last_refill"] = now
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True
            return False

    def get_wait_time(self, client_ip: str) -> float:
        if self._rpm <= 0:
            return 0
        bucket = self._buckets.get(client_ip)
        if not bucket or bucket["tokens"] >= 1:
            return 0
        refill_rate = self._rpm / 60.0
        deficit = 1 - bucket["tokens"]
        return deficit / refill_rate if refill_rate > 0 else 1


# ── Provider Manager ────────────────────────────────
class ProviderManager:
    def __init__(self):
        self.providers = load_providers()
        self.api_keys = load_api_keys()
        self.config = load_proxy_config()
        self.stats = StatsDB()
        self._error_counts: dict = defaultdict(int)
        self._last_error_time: dict = defaultdict(float)
        self._cooldown_until: dict = defaultdict(float)
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
            if time.time() < self._cooldown_until[pid]:
                continue
            models = provider.get("models", [])
            if model_filter:
                models = [m for m in models if model_filter in m["id"]]
            if models:
                available.append(
                    {
                        "id": pid,
                        "name": provider["name"],
                        "api_base": provider["api_base"],
                        "models": models,
                        "speed": provider.get("speed", ""),
                        "signup_url": provider.get("signup_url", ""),
                    }
                )
        available.sort(
            key=lambda p: max((m.get("priority", 0) for m in p["models"]), default=0),
            reverse=True,
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
        self._error_counts[provider_id] += 1
        self._last_error_time[provider_id] = time.time()
        count = self._error_counts[provider_id]
        if count >= 3:
            cooldown = min(30 * (2 ** (count - 3)), 300)
            self._cooldown_until[provider_id] = time.time() + cooldown
            log.warning(f"Provider {provider_id} cooldown {cooldown}s (error #{count}): {error}")
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
        for f in CACHE_DIR.glob("*.json"):
            f.unlink(missing_ok=True)

    def get_stats(self):
        files = list(CACHE_DIR.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "entries": len(files),
            "total_size_kb": round(total_size / 1024, 1),
            "enabled": self._enabled,
            "ttl_seconds": self._ttl,
        }


# ── HTTP Client Pool ────────────────────────────────
_http_client: httpx.Client | None = None
_http_client_lock = threading.Lock()


def get_http_client(timeout=60):
    global _http_client
    with _http_client_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = httpx.Client(
                timeout=timeout,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                http2=True,
            )
        return _http_client


def close_http_client():
    global _http_client
    with _http_client_lock:
        if _http_client and not _http_client.is_closed:
            _http_client.close()
            _http_client = None


# ── Globals ─────────────────────────────────────────
ROUTERAI_API_KEY = os.environ.get("ROUTERAI_API_KEY", "")
CORS_ORIGINS = os.environ.get("ROUTERAI_CORS_ORIGINS", "http://localhost:*,http://127.0.0.1:*").split(",")

manager = ProviderManager()
cache = ResponseCache()
rate_limiter = RateLimiter()


# ── FastAPI App ─────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    cache.update_config(manager.config.get("cache_enabled", True), manager.config.get("cache_ttl", 3600))
    rate_limiter.configure(manager.config.get("rate_limit_rpm", 0))
    log.info("RouterAI started")
    yield
    # Shutdown — flush stats and close connections
    manager.stats.close()
    close_http_client()
    log.info("RouterAI stopped")


app = FastAPI(
    title="RouterAI",
    description="OpenAI-compatible API proxy with auto-failover",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — restrict to localhost by default
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth + Rate Limit Middleware ─────────────────────
@app.middleware("http")
async def auth_and_rate_limit(request: Request, call_next):
    path = request.url.path

    # Skip auth for health, static, dashboard UI, dashboard API
    if path == "/health" or path.startswith("/static"):
        return await call_next(request)

    # Dashboard pages and API — no auth, but rate limit
    if path == "/" or path.startswith("/api/"):
        client_ip = request.client.host if request.client else "unknown"
        if not rate_limiter.is_allowed(client_ip):
            wait = rate_limiter.get_wait_time(client_ip)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": f"Rate limit exceeded. Try again in {wait:.1f}s",
                        "type": "rate_limit_error",
                        "retry_after": round(wait, 1),
                    }
                },
            )
        return await call_next(request)

    # /v1/* endpoints — auth + rate limit
    if path.startswith("/v1/"):
        if ROUTERAI_API_KEY:
            auth = request.headers.get("Authorization", "")
            key_valid = (auth.startswith("Bearer ") and auth[7:] == ROUTERAI_API_KEY) or (
                request.query_params.get("key") == ROUTERAI_API_KEY
            )
            if not key_valid:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": {
                            "message": "Invalid or missing API key. Set ROUTERAI_API_KEY env var.",
                            "type": "authentication_error",
                            "code": "invalid_api_key",
                        }
                    },
                )

        client_ip = request.client.host if request.client else "unknown"
        if not rate_limiter.is_allowed(client_ip):
            wait = rate_limiter.get_wait_time(client_ip)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": f"Rate limit exceeded. Try again in {wait:.1f}s",
                        "type": "rate_limit_error",
                        "retry_after": round(wait, 1),
                    }
                },
            )

    return await call_next(request)


# ══════════════════════════════════════════════════════
#  OpenAI-Compatible Proxy Endpoints
# ══════════════════════════════════════════════════════


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible model list."""
    available = manager.get_available_providers()
    models = []
    for p in available:
        for m in p["models"]:
            models.append(
                {
                    "id": f"{p['id']}/{m['id']}",
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": p["name"],
                    "free": m.get("free", False),
                    "context_length": m.get("context", 0),
                }
            )
    return {"object": "list", "data": models}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions with auto-failover."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Request must be JSON", "type": "invalid_request_error"}},
        )

    if not body:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Request body is empty", "type": "invalid_request_error"}},
        )

    messages = body.get("messages", [])
    if not messages:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Missing required field: messages", "type": "invalid_request_error"}},
        )

    requested_model = body.get("model", "llama-3.3-70b-versatile")
    stream = body.get("stream", False)

    # Check cache
    cached = cache.get(messages, requested_model)
    if cached:
        log.info(f"Cache hit for model={requested_model}")
        if stream:
            return StreamingResponse(_stream_from_cache(cached), media_type="text/event-stream")
        return cached

    # Try providers with failover + exponential retry
    tried = set()
    max_retries = manager.config.get("max_retries", 3)
    last_error = None

    for attempt in range(max_retries):
        provider, model = manager.resolve_model(requested_model)
        if not provider or not model:
            break

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
                return StreamingResponse(
                    _stream_request(provider, model, body, api_key, messages, requested_model),
                    media_type="text/event-stream",
                )

            result = _make_request(provider, model, body, api_key)
            latency = int((time.time() - start_time) * 1000)

            if "error" in result:
                raise Exception(result.get("error", {}).get("message", "Unknown error"))

            manager.report_success(provider["id"])
            usage = result.get("usage", {})
            manager.stats.record(
                provider["id"],
                model["id"],
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                latency,
                True,
            )
            cache.set(messages, requested_model, result)
            return result

        except httpx.HTTPStatusError as e:
            last_error = str(e)
            if e.response.status_code == 429:
                retry_after = float(e.response.headers.get("Retry-After", 2))
                log.warning(f"Rate limited by {provider['id']}, waiting {retry_after}s")
                import asyncio

                await asyncio.sleep(min(retry_after, 5))
                tried.discard(provider["id"])
                continue
            manager.report_error(provider["id"], last_error)
            manager.stats.record(provider["id"], model.get("id", "?"), 0, 0, 0, False, last_error)

        except Exception as e:
            last_error = str(e)
            manager.report_error(provider["id"], last_error)
            manager.stats.record(provider["id"], model.get("id", "?"), 0, 0, 0, False, last_error)

    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "message": f"ทุก provider ล้มเหลว ({len(tried)} ตัว): {last_error or 'no providers available'}",
                "type": "all_providers_failed",
                "code": "provider_exhausted",
            }
        },
    )


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    """OpenAI-compatible embeddings endpoint."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Request must be JSON", "type": "invalid_request_error"}},
        )

    input_text = body.get("input", "")
    if not input_text:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Missing required field: input", "type": "invalid_request_error"}},
        )

    requested_model = body.get("model", "text-embedding-ada-002")

    # Try providers that support embeddings
    tried = set()
    for attempt in range(3):
        provider, model = manager.resolve_model(requested_model)
        if not provider:
            break
        if provider["id"] in tried:
            available = manager.get_available_providers()
            for p in available:
                if p["id"] not in tried:
                    provider = p
                    model = p["models"][0]
                    break
            else:
                break
        tried.add(provider["id"])
        api_key = manager.get_api_key(provider["id"])

        try:
            url = f"{provider['api_base']}/embeddings"
            headers = {"Content-Type": "application/json"}
            if api_key and api_key != "ollama":
                headers["Authorization"] = f"Bearer {api_key}"
            payload = {"input": input_text, "model": model["id"]}
            client = get_http_client(60)
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()
            manager.report_success(provider["id"])
            return result
        except Exception as e:
            last_error = str(e)
            manager.report_error(provider["id"], last_error)
            continue

    return JSONResponse(
        status_code=503,
        content={"error": {"message": "No provider supports embeddings or all failed", "type": "provider_exhausted"}},
    )


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


async def _stream_request(provider, model, body, api_key, messages, requested_model):
    """Stream a request to a provider with failover error reporting."""
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
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
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


async def _stream_from_cache(cached):
    """Convert cached response to SSE stream."""
    import asyncio

    choices = cached.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")
        chunk_size = max(1, len(content) // 50)
        for i in range(0, len(content), chunk_size):
            piece = content[i : i + chunk_size]
            chunk = {"choices": [{"delta": {"content": piece}, "index": 0}]}
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0.01)
    yield "data: [DONE]\n\n"


# ══════════════════════════════════════════════════════
#  Dashboard UI
# ══════════════════════════════════════════════════════
@app.get("/")
async def index():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse(status_code=404, content={"error": "Dashboard not found"})


# ══════════════════════════════════════════════════════
#  Dashboard API
# ══════════════════════════════════════════════════════
@app.get("/api/status")
async def api_status():
    available = manager.get_available_providers()
    summary = manager.stats.get_summary(days=7)
    return {
        "status": "running",
        "version": "2.0.0",
        "providers_total": len(manager.providers),
        "providers_available": len(available),
        "config": manager.config,
        "stats": summary,
        "cache": cache.get_stats(),
        "rate_limit_rpm": manager.config.get("rate_limit_rpm", 0),
    }


@app.get("/api/providers")
async def api_providers():
    manager.reload()
    cache.update_config(manager.config.get("cache_enabled", True), manager.config.get("cache_ttl", 3600))
    rate_limiter.configure(manager.config.get("rate_limit_rpm", 0))

    available_ids = {p["id"] for p in manager.get_available_providers()}
    result = []

    for pid, provider in manager.providers.items():
        env_key = provider.get("api_key_env")
        has_key = bool(
            (env_key and manager.api_keys.get(env_key)) or (env_key and os.environ.get(env_key)) or not env_key
        )

        health = {}
        error_count = manager._error_counts.get(pid, 0)
        cooldown = manager._cooldown_until.get(pid, 0)

        result.append(
            {
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
                    "last_check": health.get("last_check"),
                },
            }
        )

    return {"providers": result}


@app.post("/api/keys")
async def api_save_keys(request: Request):
    data = await request.json()
    manager.save_api_keys(data)
    manager.reload()
    return {"status": "ok", "message": "บันทึก API Key เรียบร้อย ✅"}


@app.get("/api/config")
async def api_config_get():
    return load_proxy_config()


@app.post("/api/config")
async def api_config_post(request: Request):
    data = await request.json()
    current = load_proxy_config()
    current.update(data)
    save_json_file(PROXY_CONFIG_FILE, current)
    manager.reload()
    cache.update_config(manager.config.get("cache_enabled", True), manager.config.get("cache_ttl", 3600))
    rate_limiter.configure(manager.config.get("rate_limit_rpm", 0))
    return {"status": "ok", "message": "บันทึกการตั้งค่าเรียบร้อย ✅"}


@app.post("/api/cache/clear")
async def api_cache_clear():
    cache.clear()
    return {"status": "ok", "message": "ล้าง cache เรียบร้อย ✅"}


@app.get("/api/cache/stats")
async def api_cache_stats():
    return cache.get_stats()


@app.post("/api/openclaw-config")
async def api_openclaw_config(request: Request):
    data = await request.json()
    provider_id = data.get("provider", "groq")
    model_id = data.get("model", "llama-3.3-70b-versatile")
    port = int(os.environ.get("ROUTERAI_PORT", 8900))

    config = {
        "llm": {
            "provider": "openai",
            "baseUrl": f"http://127.0.0.1:{port}/v1",
            "apiKey": "routerai",
            "model": f"{provider_id}/{model_id}",
        }
    }

    return {
        "config": config,
        "instructions": "คัดลอก config นี้ไปวางใน ~/.openclaw/openclaw.json แล้วรัน openclaw restart",
    }


@app.get("/api/stats")
async def api_stats(days: int = 7):
    return manager.stats.get_summary(days=days)


@app.post("/api/test/{provider_id}")
async def api_test_provider(provider_id: str):
    provider = manager.providers.get(provider_id)
    if not provider:
        return JSONResponse(status_code=404, content={"error": "ไม่พบ provider"})

    api_key = manager.get_api_key(provider_id)
    if not api_key:
        return JSONResponse(status_code=400, content={"error": "ไม่พบ API Key"})

    model = provider["models"][0]
    try:
        start = time.time()
        result = _make_request(
            provider,
            model,
            {"messages": [{"role": "user", "content": "สวัสดี ตอบสั้นๆ ว่าใช้งานได้"}], "max_tokens": 50},
            api_key,
        )
        latency = int((time.time() - start) * 1000)

        if "error" in result:
            return {"success": False, "error": result["error"], "latency_ms": latency}

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"success": True, "response": content, "latency_ms": latency, "model": model["id"]}

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/models/compare")
async def api_compare_models(request: Request):
    """Send the same prompt to multiple models and compare."""
    data = await request.json()
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
            result = _make_request(
                provider, model, {"messages": [{"role": "user", "content": prompt}], "max_tokens": 200}, api_key
            )
            latency = int((time.time() - start) * 1000)
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            results.append(
                {"provider": pid, "model": model["id"], "response": content, "latency_ms": latency, "success": True}
            )
        except Exception as e:
            results.append({"provider": pid, "model": model.get("id", "?"), "error": str(e), "success": False})

    return {"results": results}


# ── Search Free Providers ───────────────────────────
@app.get("/api/search-free-providers")
async def api_search_free_providers(q: str = ""):
    """Search for free AI providers/models from OpenRouter + curated list."""
    results = []

    # Curated free providers list (always available)
    curated = [
        {"provider": "Groq", "model": "llama-3.3-70b-versatile", "free": True, "context": 131072, "speed": "เร็วมาก", "category": "chat", "signup": "https://console.groq.com/keys", "flag": "🇺🇸"},
        {"provider": "Groq", "model": "llama-3.1-8b-instant", "free": True, "context": 131072, "speed": "เร็วสุดๆ", "category": "chat", "signup": "https://console.groq.com/keys", "flag": "🇺🇸"},
        {"provider": "Groq", "model": "gemma2-9b-it", "free": True, "context": 8192, "speed": "เร็ว", "category": "chat", "signup": "https://console.groq.com/keys", "flag": "🇺🇸"},
        {"provider": "Cerebras", "model": "llama3.1-70b", "free": True, "context": 8192, "speed": "เร็วมาก", "category": "chat", "signup": "https://cloud.cerebras.ai", "flag": "🇺🇸"},
        {"provider": "Cerebras", "model": "llama3.1-8b", "free": True, "context": 8192, "speed": "เร็วสุดๆ", "category": "chat", "signup": "https://cloud.cerebras.ai", "flag": "🇺🇸"},
        {"provider": "Google Gemini", "model": "gemini-2.0-flash", "free": True, "context": 1048576, "speed": "เร็ว", "category": "vision", "signup": "https://aistudio.google.com/apikey", "flag": "🇺🇸"},
        {"provider": "Google Gemini", "model": "gemini-1.5-flash", "free": True, "context": 1048576, "speed": "เร็ว", "category": "vision", "signup": "https://aistudio.google.com/apikey", "flag": "🇺🇸"},
        {"provider": "Mistral", "model": "mistral-small-latest", "free": True, "context": 32768, "speed": "ปานกลาง", "category": "chat", "signup": "https://console.mistral.ai/api-keys/", "flag": "🇫🇷"},
        {"provider": "NVIDIA", "model": "llama-3.1-70b-instruct", "free": True, "context": 131072, "speed": "เร็ว", "category": "chat", "signup": "https://build.nvidia.com/explore/discover", "flag": "🇺🇸"},
        {"provider": "SiliconFlow", "model": "Qwen2.5-72B-Instruct", "free": True, "context": 32768, "speed": "ปานกลาง", "category": "chat", "signup": "https://cloud.siliconflow.cn", "flag": "🇨🇳"},
        {"provider": "SiliconFlow", "model": "DeepSeek-V2.5", "free": True, "context": 65536, "speed": "ปานกลาง", "category": "code", "signup": "https://cloud.siliconflow.cn", "flag": "🇨🇳"},
        {"provider": "OpenRouter", "model": "llama-3.1-8b-instruct:free", "free": True, "context": 131072, "speed": "ปานกลาง", "category": "chat", "signup": "https://openrouter.ai/settings/keys", "flag": "🌍"},
        {"provider": "OpenRouter", "model": "gemma-2-9b-it:free", "free": True, "context": 8192, "speed": "ปานกลาง", "category": "chat", "signup": "https://openrouter.ai/settings/keys", "flag": "🌍"},
        {"provider": "Chutes AI", "model": "llama-3.1-70b-instruct", "free": True, "context": 131072, "speed": "ปานกลาง", "category": "chat", "signup": "https://chutes.ai", "flag": "🌍"},
        {"provider": "Together AI", "model": "Llama-3.3-70B (ทดลอง)", "free": False, "context": 131072, "speed": "ปานกลาง", "category": "chat", "signup": "https://api.together.xyz/settings/api-keys", "flag": "🇺🇸", "note": "$5 เครดิตฟรี"},
        {"provider": "Ollama (Local)", "model": "llama3.1", "free": True, "context": 131072, "speed": "เร็ว (local)", "category": "chat", "signup": "https://ollama.com", "flag": "🏠"},
    ]

    # Also try to fetch from OpenRouter
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://openrouter.ai/api/v1/models")
            if resp.status_code == 200:
                or_models = resp.json().get("data", [])
                for m in or_models:
                    mid = m.get("id", "")
                    pricing = m.get("pricing", {})
                    prompt_price = float(pricing.get("prompt", "1"))
                    is_free = prompt_price == 0 or ":free" in mid
                    if is_free:
                        results.append({
                            "provider": "OpenRouter",
                            "model": mid,
                            "free": True,
                            "context": m.get("context_length", 0),
                            "speed": "—",
                            "category": "openrouter",
                            "signup": "https://openrouter.ai/settings/keys",
                            "flag": "🌍",
                            "description": m.get("name", ""),
                        })
    except Exception:
        pass  # Silently fail, curated list is enough

    # Filter by search query
    if q:
        q_lower = q.lower()
        curated = [r for r in curated if q_lower in r["model"].lower() or q_lower in r["provider"].lower() or q_lower in r.get("category", "").lower()]
        results = [r for r in results if q_lower in r["model"].lower() or q_lower in r["provider"].lower()]

    # Merge: curated first, then OpenRouter
    all_results = curated + results[:50]  # Limit OpenRouter results

    return {"total": len(all_results), "results": all_results}


# ── Analytics ───────────────────────────────────────
@app.get("/api/analytics")
async def api_analytics(days: int = 7):
    """Detailed usage analytics with daily breakdown."""
    summary = manager.stats.get_summary(days=days)

    # Provider breakdown from current config
    provider_stats = []
    for pid, pdata in manager.providers.items():
        key = manager.get_api_key(pid)
        models = pdata.get("models", [])
        free_count = sum(1 for m in models if m.get("free", False))
        provider_stats.append({
            "id": pid,
            "name": pdata.get("name", pid),
            "flag": pdata.get("flag", ""),
            "has_key": bool(key),
            "total_models": len(models),
            "free_models": free_count,
            "paid_models": len(models) - free_count,
            "speed": pdata.get("speed", ""),
            "signup_url": pdata.get("signup_url", ""),
        })

    # Token estimate (rough)
    total_tokens = summary.get("total_tokens_in", 0) + summary.get("total_tokens_out", 0)

    return {
        "period_days": days,
        "summary": {
            "total_requests": summary.get("total_requests", 0),
            "successful_requests": summary.get("successful_requests", 0),
            "failed_requests": summary.get("failed_requests", 0),
            "success_rate": round(summary.get("success_rate", 0), 1),
            "total_tokens_in": summary.get("total_tokens_in", 0),
            "total_tokens_out": summary.get("total_tokens_out", 0),
            "total_tokens": total_tokens,
            "avg_latency_ms": round(summary.get("avg_latency_ms", 0)),
            "providers_available": len(manager.get_available_providers()),
            "providers_total": len(manager.providers),
        },
        "daily": summary.get("daily", []),
        "providers": provider_stats,
        "cache": manager.cache.get_stats() if manager.cache.enabled else {"enabled": False},
    }


# ── Chat Playground ─────────────────────────────────
@app.post("/api/playground/chat")
async def api_playground_chat(request: Request):
    """Chat playground — sends a message to a specific provider/model."""
    data = await request.json()
    provider_id = data.get("provider", "")
    model_id = data.get("model", "")
    message = data.get("message", "")
    system_prompt = data.get("system_prompt", "")

    if not message:
        return JSONResponse(status_code=400, content={"error": "กรุณาใส่ข้อความ"})

    provider = manager.providers.get(provider_id)
    if not provider:
        return JSONResponse(status_code=404, content={"error": f"ไม่พบ provider: {provider_id}"})

    api_key = manager.get_api_key(provider_id)
    if not api_key and provider.get("api_key_env"):
        return JSONResponse(status_code=400, content={"error": f"ไม่พบ API Key สำหรับ {provider.get('name', provider_id)}"})

    # Find model
    model = None
    for m in provider.get("models", []):
        if m["id"] == model_id:
            model = m
            break
    if not model:
        model = provider["models"][0] if provider.get("models") else {"id": model_id}

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": message})

    try:
        start = time.time()
        result = _make_request(provider, model, {"messages": messages, "max_tokens": 1024}, api_key)
        latency = int((time.time() - start) * 1000)

        if "error" in result:
            return {"success": False, "error": result["error"], "latency_ms": latency}

        choice = result.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        usage = result.get("usage", {})

        return {
            "success": True,
            "response": content,
            "model": model["id"],
            "provider": provider_id,
            "latency_ms": latency,
            "usage": usage,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "latency_ms": 0}


# ── Health Check ────────────────────────────────────
@app.get("/health")
async def health():
    available = manager.get_available_providers()
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "providers_available": len(available),
        "providers_total": len(manager.providers),
        "version": "2.0.0",
    }


# ── Main ────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("ROUTERAI_PORT", 8900))
    host = os.environ.get("ROUTERAI_HOST", "127.0.0.1")
    debug = os.environ.get("ROUTERAI_DEBUG", "").lower() in ("1", "true", "yes")

    print(f"""
╔══════════════════════════════════════════════════╗
║  🔀 RouterAI v2.0.0 — FastAPI Server           ║
║  🌐 Proxy + Dashboard: http://{host}:{port}      ║
║  📊 API Docs:     http://{host}:{port}/docs      ║
╚══════════════════════════════════════════════════╝
    """)

    uvicorn.run("server:app", host=host, port=port, reload=debug, log_level=LOG_LEVEL.lower())
