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
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

# ── Config ──────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
PROVIDERS_FILE = BASE_DIR / "providers.json"
CUSTOM_PROVIDERS_FILE = DATA_DIR / "custom_providers.json"
API_KEYS_FILE = DATA_DIR / "api_keys.json"
ENCRYPTION_KEY_FILE = DATA_DIR / ".encryption_key"
PROXY_CONFIG_FILE = DATA_DIR / "proxy_config.json"
# Legacy paths for migration (pre-Docker or old layout)
_LEGACY_API_KEYS_FILE = BASE_DIR / "api_keys.json"
_LEGACY_PROXY_CONFIG_FILE = BASE_DIR / "proxy_config.json"
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


# ── Safe Migration: legacy → DATA_DIR ───────────────
def _migrate_legacy_file(legacy_path: Path, new_path: Path) -> None:
    """
    If legacy file exists at old location but not at new DATA_DIR path,
    safely copy it over. Never overwrites existing new-path files.
    """
    if legacy_path.exists() and not new_path.exists():
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(legacy_path), str(new_path))
            log.info(f"Migrated {legacy_path.name} → {new_path}")
        except Exception as e:
            log.error(f"Failed to migrate {legacy_path} → {new_path}: {e}")

# Run migration on module load (before any load_json_file call)
DATA_DIR.mkdir(parents=True, exist_ok=True)
_migrate_legacy_file(_LEGACY_API_KEYS_FILE, API_KEYS_FILE)
_migrate_legacy_file(_LEGACY_PROXY_CONFIG_FILE, PROXY_CONFIG_FILE)


# ── Load Config Helpers ─────────────────────────────
def load_json_file(path: Path, default=None):
    """Safely load a JSON file with fallback."""
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.error(f"Failed to load {path}: {e}")
    return default or {}


def load_providers():
    """Load built-in + custom providers, merged together."""
    built_in = load_json_file(PROVIDERS_FILE, {})
    custom = load_json_file(CUSTOM_PROVIDERS_FILE, {})
    # Custom providers override built-in if same ID
    merged = {**built_in, **custom}
    return merged


def load_custom_providers():
    """Load only user-added custom providers."""
    return load_json_file(CUSTOM_PROVIDERS_FILE, {})


def save_custom_providers(providers: dict):
    """Save custom providers to separate file."""
    save_json_file(CUSTOM_PROVIDERS_FILE, providers)


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
        "timeout": 30,           # non-streaming timeout (seconds)
        "stream_timeout": 60,    # streaming timeout (seconds)
        "rate_limit_rpm": 0,     # 0 = unlimited (per IP)
        "rate_limit_rpm_per_key": 0,  # 0 = unlimited (per API key)
    }
    cfg = load_json_file(PROXY_CONFIG_FILE, {})
    defaults.update(cfg)
    return defaults


def save_json_file(path: Path, data):
    """Write JSON to file with proper encoding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def mask_key(key: str) -> str:
    """Mask an API key, showing only last 4 characters: sk-...xxxx"""
    if not key or len(key) < 8:
        return key or ""
    return f"{key[:3]}...{key[-4:]}"


# ── Encrypted Key Store ─────────────────────────────
class KeyStore:
    """
    Encrypted API key storage using Fernet (AES-128-CBC).
    Keys are encrypted at rest in api_keys.json.
    The encryption key is stored in data/.encryption_key (auto-generated).
    Falls back to plaintext for backward compatibility.
    """

    def __init__(self):
        self._fernet = None
        self._init_encryption()

    def _init_encryption(self):
        """Initialize Fernet encryption. Generate key if not exists."""
        try:
            from cryptography.fernet import Fernet

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            if ENCRYPTION_KEY_FILE.exists():
                key = ENCRYPTION_KEY_FILE.read_bytes().strip()
            else:
                key = Fernet.generate_key()
                ENCRYPTION_KEY_FILE.write_bytes(key)
                # Restrict permissions
                import stat

                ENCRYPTION_KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
                log.info("Generated new encryption key for API key storage")
            self._fernet = Fernet(key)
        except ImportError:
            log.warning("cryptography library not found — API keys stored in plaintext. Install: pip install cryptography")
            self._fernet = None
        except Exception as e:
            log.error(f"Failed to init encryption: {e}")
            self._fernet = None

    def is_encrypted(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a key value. Returns 'ENC:<base64>' prefix string."""
        if not self._fernet:
            return plaintext
        encrypted = self._fernet.encrypt(plaintext.encode())
        return f"ENC:{encrypted.decode()}"

    def decrypt(self, stored_value: str) -> str:
        """Decrypt a stored value. Handles both encrypted and legacy plaintext."""
        if not stored_value:
            return ""
        if stored_value.startswith("ENC:"):
            if not self._fernet:
                log.error("Cannot decrypt: cryptography not available")
                return ""
            try:
                return self._fernet.decrypt(stored_value[4:].encode()).decode()
            except Exception as e:
                log.error(f"Decryption failed: {e}")
                return ""
        # Legacy plaintext — still works, will be re-encrypted on next save
        return stored_value

    def load_keys(self) -> dict:
        """Load and decrypt all API keys."""
        raw = load_json_file(API_KEYS_FILE, {})
        return {k: self.decrypt(v) for k, v in raw.items()}

    def save_keys(self, keys: dict) -> None:
        """Encrypt and save API keys. Merges with existing. Empty values → delete key."""
        existing = load_json_file(API_KEYS_FILE, {})
        for k, v in keys.items():
            if v:
                existing[k] = self.encrypt(v)
            else:
                existing.pop(k, None)  # Delete key on empty value
        save_json_file(API_KEYS_FILE, existing)

    def get_masked_keys(self) -> dict:
        """Return all keys masked for display: sk-...xxxx"""
        raw = load_json_file(API_KEYS_FILE, {})
        decrypted = {k: self.decrypt(v) for k, v in raw.items()}
        return {k: mask_key(v) for k, v in decrypted.items() if v}


key_store = KeyStore()


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

    def _ensure_conn(self):
        """Reconnect if connection was closed (e.g. by lifespan shutdown in tests)."""
        try:
            self._conn.execute("SELECT 1")
        except (sqlite3.ProgrammingError, sqlite3.InterfaceError):
            self._conn = sqlite3.connect(str(STATS_DB), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._init_tables()

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
                    cost_usd REAL DEFAULT 0,
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
            # Migrate: add cost_usd column if missing (older DBs)
            try:
                self._conn.execute("SELECT cost_usd FROM requests LIMIT 1")
            except sqlite3.OperationalError:
                self._conn.execute("ALTER TABLE requests ADD COLUMN cost_usd REAL DEFAULT 0")
                log.info("Migrated stats DB: added cost_usd column")
            self._conn.commit()

    def _cleanup_old(self):
        self._ensure_conn()
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        with self._lock:
            self._conn.execute("DELETE FROM requests WHERE ts < ?", (cutoff,))
            self._conn.commit()

    def record(self, provider, model, tokens_in, tokens_out, latency_ms, success, error=None, cost_usd=0.0):
        self._ensure_conn()
        now = datetime.now().isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO requests (ts, provider, model, tokens_in, tokens_out, cost_usd, latency_ms, success, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, provider, model, tokens_in, tokens_out, round(cost_usd, 6), latency_ms, int(success), error),
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
        self._ensure_conn()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*), SUM(success), SUM(CASE WHEN success=0 THEN 1 ELSE 0 END), "
                "SUM(tokens_in), SUM(tokens_out), AVG(latency_ms), SUM(cost_usd) "
                "FROM requests WHERE ts > ?",
                (cutoff,),
            )
            row = cur.fetchone()
            total = row[0] or 0
            success_count = row[1] or 0
            fail_count = row[2] or 0
            total_tokens_in = row[3] or 0
            total_tokens_out = row[4] or 0
            avg_latency = round(row[5] or 0)
            total_cost = round(row[6] or 0, 4)

            # By provider
            cur = self._conn.execute(
                "SELECT provider, COUNT(*), SUM(success), SUM(tokens_in + tokens_out), AVG(latency_ms), SUM(cost_usd) "
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
                    "cost_usd": round(prow[5] or 0, 4),
                }

            # Daily breakdown
            cur = self._conn.execute(
                "SELECT SUBSTR(ts, 1, 10) AS day, COUNT(*), SUM(success), SUM(tokens_in + tokens_out), SUM(cost_usd) "
                "FROM requests WHERE ts > ? GROUP BY day ORDER BY day",
                (cutoff,),
            )
            daily = []
            for drow in cur.fetchall():
                daily.append({
                    "date": drow[0],
                    "requests": drow[1],
                    "success": drow[2] or 0,
                    "tokens": drow[3] or 0,
                    "cost_usd": round(drow[4] or 0, 4),
                })

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
            "successful_requests": success_count,
            "failed_requests": fail_count,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "total_cost_usd": total_cost,
            "avg_latency_ms": avg_latency,
            "by_provider": by_provider,
            "daily": daily,
            "provider_health": provider_health,
        }

    def get_daily_cost(self):
        """Return today's total cost in USD."""
        self._ensure_conn()
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            cur = self._conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM requests WHERE SUBSTR(ts, 1, 10) = ?",
                (today,),
            )
            return round(cur.fetchone()[0], 4)

    def get_latency_stats(self, days=7):
        """Return per-provider latency stats (p50, p95, avg)."""
        self._ensure_conn()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "SELECT provider, latency_ms FROM requests WHERE ts > ? AND success = 1 ORDER BY provider, latency_ms",
                (cutoff,),
            )
            rows = cur.fetchall()

        from collections import defaultdict
        by_provider = defaultdict(list)
        for prov, lat in rows:
            by_provider[prov].append(lat)

        result = {}
        for prov, lats in by_provider.items():
            n = len(lats)
            result[prov] = {
                "count": n,
                "avg_ms": round(sum(lats) / n),
                "p50_ms": lats[n // 2],
                "p95_ms": lats[int(n * 0.95)] if n > 1 else lats[0],
                "min_ms": lats[0],
                "max_ms": lats[-1],
            }
        return {"providers": result, "period_days": days}

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.ProgrammingError:
                pass  # Already closed


# ── Rate Limiter ────────────────────────────────────
class RateLimiter:
    """Token-bucket rate limiter per client identity (IP + API key)."""

    def __init__(self):
        self._buckets: dict = {}
        self._lock = threading.Lock()
        self._rpm = 0
        self._rpm_per_key = 0

    def configure(self, rpm: int, rpm_per_key: int = 0):
        self._rpm = rpm
        self._rpm_per_key = rpm_per_key
        self._buckets.clear()

    def _get_bucket(self, identity: str, limit: int):
        if identity not in self._buckets:
            self._buckets[identity] = {"tokens": limit, "last_refill": time.time()}
        return self._buckets[identity]

    def _check_bucket(self, identity: str, limit: int) -> bool:
        """Check and consume from a specific bucket. Returns True if allowed."""
        if limit <= 0:
            return True
        with self._lock:
            bucket = self._get_bucket(identity, limit)
            now = time.time()
            elapsed = now - bucket["last_refill"]
            refill_rate = limit / 60.0
            bucket["tokens"] = min(limit, bucket["tokens"] + elapsed * refill_rate)
            bucket["last_refill"] = now
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                return True
            return False

    def is_allowed(self, client_ip: str, api_key: str = "") -> bool:
        # Check per-IP limit
        if not self._check_bucket(f"ip:{client_ip}", self._rpm):
            return False
        # Check per-key limit
        if api_key and self._rpm_per_key > 0:
            return self._check_bucket(f"key:{api_key}", self._rpm_per_key)
        return True

    def _get_bucket_wait(self, identity: str, limit: int) -> float:
        bucket = self._buckets.get(identity)
        if not bucket or bucket["tokens"] >= 1:
            return 0
        refill_rate = limit / 60.0
        deficit = 1 - bucket["tokens"]
        return deficit / refill_rate if refill_rate > 0 else 1

    def get_wait_time(self, client_ip: str, api_key: str = "") -> float:
        wait_ip = self._get_bucket_wait(f"ip:{client_ip}", self._rpm) if self._rpm > 0 else 0
        wait_key = 0
        if api_key and self._rpm_per_key > 0:
            wait_key = self._get_bucket_wait(f"key:{api_key}", self._rpm_per_key)
        return max(wait_ip, wait_key)


# ── Provider Manager ────────────────────────────────
class ProviderManager:
    def __init__(self):
        self.providers = load_providers()
        self.api_keys = key_store.load_keys()
        self.config = load_proxy_config()
        self.stats = StatsDB()
        self._error_counts: dict = defaultdict(int)
        self._last_error_time: dict = defaultdict(float)
        self._cooldown_until: dict = defaultdict(float)
        self._reload_keys_from_env()

    def _reload_keys_from_env(self):
        for _pid, provider in self.providers.items():
            env_key = provider.get("api_key_env")
            if env_key and env_key not in self.api_keys:
                val = os.environ.get(env_key)
                if val:
                    self.api_keys[env_key] = val

    def get_available_providers(self, model_filter=None, vision_only=False):
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
            if vision_only:
                models = [m for m in models if m.get("vision")]
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
        key_store.save_keys(keys)
        self.api_keys = key_store.load_keys()

    def calc_cost(self, provider_id, model_id, tokens_in, tokens_out):
        """Calculate cost in USD for a request based on provider's cost_per_1k."""
        provider = self.providers.get(provider_id, {})
        for m in provider.get("models", []):
            if m["id"] == model_id:
                cost_per_1k = m.get("cost_per_1k", 0)
                if cost_per_1k:
                    return (tokens_in + tokens_out) / 1000.0 * cost_per_1k
                return 0.0
        return 0.0

    def check_budget(self):
        """Check if daily budget is exceeded. Returns (exceeded, spent, limit)."""
        limit = self.config.get("budget_daily_usd", 0)
        if limit <= 0:
            return False, 0, 0
        spent = self.stats.get_daily_cost()
        return spent >= limit, spent, limit

    def reload(self):
        self.providers = load_providers()
        self.api_keys = key_store.load_keys()
        self.config = load_proxy_config()
        self._reload_keys_from_env()


# ── Response Cache ──────────────────────────────────
class ResponseCache:
    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._enabled = True
        self._ttl = 3600
        self._hits = 0
        self._misses = 0

    def update_config(self, enabled, ttl):
        self._enabled = enabled
        self._ttl = ttl

    # Parameters that affect model output and must be included in cache key
    _CACHE_PARAMS = ("temperature", "top_p", "max_tokens", "frequency_penalty",
                     "presence_penalty", "stop", "seed", "n")

    def _key(self, messages, model, params=None):
        cache_data = {"messages": messages, "model": model}
        if params:
            for p in self._CACHE_PARAMS:
                if p in params:
                    cache_data[p] = params[p]
        content = json.dumps(cache_data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, messages, model, params=None):
        if not self._enabled:
            return None
        key = self._key(messages, model, params)
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            age = time.time() - path.stat().st_mtime
            if age < self._ttl:
                try:
                    with open(path) as f:
                        result = json.load(f)
                    self._hits += 1
                    return result
                except (json.JSONDecodeError, OSError):
                    pass
        self._misses += 1
        return None

    def set(self, messages, model, response, params=None):
        key = self._key(messages, model, params)
        path = CACHE_DIR / f"{key}.json"
        save_json_file(path, response)

    def clear(self):
        for f in CACHE_DIR.glob("*.json"):
            f.unlink(missing_ok=True)

    def get_stats(self):
        files = list(CACHE_DIR.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        total_req = self._hits + self._misses
        return {
            "entries": len(files),
            "total_size_kb": round(total_size / 1024, 1),
            "enabled": self._enabled,
            "ttl_seconds": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total_req * 100, 1) if total_req > 0 else 0,
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
DASHBOARD_PASSWORD = os.environ.get("ROUTERAI_DASHBOARD_PASSWORD", "")
DASHBOARD_AUTH_ENABLED = bool(DASHBOARD_PASSWORD)
CORS_ORIGINS_ENV = os.environ.get("ROUTERAI_CORS_ORIGINS", "http://localhost:*,http://127.0.0.1:*")
# Parse CORS: support comma-separated origins, strip whitespace
CORS_ORIGINS = [o.strip() for o in CORS_ORIGINS_ENV.split(",") if o.strip()]

manager = ProviderManager()
cache = ResponseCache()
rate_limiter = RateLimiter()


# ── Dashboard Session Manager ───────────────────────
class SessionManager:
    """In-memory session store with TTL. Tokens are cryptographically random."""

    def __init__(self, ttl_hours: int = 24):
        self._sessions: dict = {}  # token -> expiry timestamp
        self._lock = threading.Lock()
        self._ttl = ttl_hours * 3600

    def create(self) -> str:
        """Create a new session, returns token."""
        token = secrets.token_hex(32)
        with self._lock:
            self._sessions[token] = time.time() + self._ttl
        return token

    def validate(self, token: str) -> bool:
        """Check if token is valid and not expired."""
        if not token:
            return False
        with self._lock:
            expiry = self._sessions.get(token)
            if expiry is None:
                return False
            if time.time() > expiry:
                del self._sessions[token]
                return False
            return True

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def cleanup(self) -> None:
        """Remove expired sessions."""
        now = time.time()
        with self._lock:
            expired = [t for t, exp in self._sessions.items() if now > exp]
            for t in expired:
                del self._sessions[t]


session_manager = SessionManager()


# ── FastAPI App ─────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    cache.update_config(manager.config.get("cache_enabled", True), manager.config.get("cache_ttl", 3600))
    rate_limiter.configure(manager.config.get("rate_limit_rpm", 0), manager.config.get("rate_limit_rpm_per_key", 0))
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

# CORS — restrict to localhost by default (tighten: no wildcard methods/headers)
_allowed_methods = ["GET", "POST", "OPTIONS"]
_allowed_headers = ["Authorization", "Content-Type", "Accept"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=_allowed_methods,
    allow_headers=_allowed_headers,
)


# ── Auth + Rate Limit Middleware ─────────────────────
@app.middleware("http")
async def auth_and_rate_limit(request: Request, call_next):
    path = request.url.path

    # Skip auth for health check
    if path == "/health":
        return await call_next(request)

    # Skip auth for login endpoint
    if path == "/api/auth/login" or path == "/api/auth/status":
        return await call_next(request)

    # Dashboard pages and API — check session if auth enabled
    if path == "/" or path.startswith("/api/"):
        # Rate limit first
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

        # Dashboard auth check
        if DASHBOARD_AUTH_ENABLED:
            token = _extract_session_token(request)
            if not session_manager.validate(token):
                # Allow the login page HTML to load
                if path == "/":
                    return await call_next(request)
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": {
                            "message": "Dashboard requires login",
                            "type": "authentication_error",
                            "code": "dashboard_auth_required",
                        }
                    },
                )

        return await call_next(request)

    # /v1/* endpoints — proxy auth + rate limit
    if path.startswith("/v1/"):
        # Extract API key from request for per-key rate limiting
        auth = request.headers.get("Authorization", "")
        provided_key = ""
        if auth.startswith("Bearer "):
            provided_key = auth[7:]
        elif request.query_params.get("key"):
            provided_key = request.query_params["key"]

        if ROUTERAI_API_KEY:
            if provided_key != ROUTERAI_API_KEY:
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
        if not rate_limiter.is_allowed(client_ip, provided_key):
            wait = rate_limiter.get_wait_time(client_ip, provided_key)
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


def _extract_session_token(request: Request) -> str:
    """Extract session token from cookie or Authorization header."""
    # Check cookie first
    token = request.cookies.get("routerai_session")
    if token:
        return token
    # Check Authorization header (Bearer token)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    # Check query param
    return request.query_params.get("session", "")


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
            entry = {
                "id": f"{p['id']}/{m['id']}",
                "object": "model",
                "created": int(time.time()),
                "owned_by": p["name"],
                "free": m.get("free", False),
                "context_length": m.get("context", 0),
            }
            if m.get("vision"):
                entry["vision"] = True
            if m.get("cost_per_1k"):
                entry["cost_per_1k"] = m["cost_per_1k"]
            models.append(entry)
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

    # Detect multimodal (vision) requests — images in message content
    has_images = False
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    has_images = True
                    break
        if has_images:
            break

    requested_model = body.get("model", "llama-3.3-70b-versatile")
    stream = body.get("stream", False)

    # Check daily budget
    budget_exceeded, budget_spent, budget_limit = manager.check_budget()
    if budget_exceeded:
        action = manager.config.get("budget_action", "downgrade")
        if action == "block":
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": f"Daily budget exceeded (${budget_spent:.2f} / ${budget_limit:.2f}). Try again tomorrow.",
                        "type": "budget_exceeded",
                        "code": "daily_budget_limit",
                    }
                },
            )
        # "downgrade" mode: prefer free models (handled by routing already)
        log.info(f"Daily budget ${budget_limit:.2f} exceeded (spent ${budget_spent:.2f}), downgrading to free models")

    # Check cache
    cached = cache.get(messages, requested_model, body)
    if cached:
        log.info(f"Cache hit for model={requested_model}")
        if stream:
            return StreamingResponse(_stream_from_cache(cached), media_type="text/event-stream")
        return cached

    # Try providers with exponential backoff retry per provider, then failover
    # Strategy: retry same provider 3 times (delay 1s→2s→4s), then move to next provider
    import asyncio

    max_retries_per_provider = manager.config.get("max_retries", 3)
    tried_providers: set = set()
    last_error = None

    # If request has images, prefer vision-capable providers
    vision_capable_ids = set()
    if has_images:
        vision_providers = manager.get_available_providers(vision_only=True)
        vision_capable_ids = {p["id"] for p in vision_providers}
        if not vision_capable_ids:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": "Request contains images but no vision-capable provider is available. Add a Gemini, OpenRouter (GPT-4o/Claude), or other vision provider key.",
                        "type": "vision_not_supported",
                        "code": "no_vision_provider",
                    }
                },
            )

    while True:
        # Pick next untried provider
        if has_images and vision_capable_ids:
            # For vision requests, resolve from vision-capable providers only
            available_vision = manager.get_available_providers(vision_only=True)
            provider, model = None, None
            for p in available_vision:
                if p["id"] not in tried_providers:
                    provider, model = p, p["models"][0]
                    break
            if not provider:
                # Fall back to resolve_model if explicit user requested a model
                provider, model = manager.resolve_model(requested_model)
        else:
            provider, model = manager.resolve_model(requested_model)

        if not provider or not model:
            break

        if provider["id"] in tried_providers:
            available = manager.get_available_providers(vision_only=has_images)
            found = False
            for p in available:
                if p["id"] not in tried_providers:
                    provider, model = p, p["models"][0]
                    found = True
                    break
            if not found:
                break

        tried_providers.add(provider["id"])
        api_key = manager.get_api_key(provider["id"])

        # Retry current provider with exponential backoff
        for retry_idx in range(max_retries_per_provider):
            try:
                start_time = time.time()

                if stream:
                    # Streaming with failover: wrap in generator that catches errors
                    remaining = [p for p in manager.get_available_providers() if p["id"] not in tried_providers]
                    return StreamingResponse(
                        _stream_with_failover(provider, model, body, api_key, messages, requested_model, remaining),
                        media_type="text/event-stream",
                    )

                result = _make_request(provider, model, body, api_key)
                latency = int((time.time() - start_time) * 1000)

                if "error" in result:
                    raise Exception(result.get("error", {}).get("message", "Unknown error"))

                manager.report_success(provider["id"])
                usage = result.get("usage", {})
                tokens_in = usage.get("prompt_tokens", 0)
                tokens_out = usage.get("completion_tokens", 0)
                cost = manager.calc_cost(provider["id"], model["id"], tokens_in, tokens_out)
                manager.stats.record(
                    provider["id"],
                    model["id"],
                    tokens_in,
                    tokens_out,
                    latency,
                    True,
                    cost_usd=cost,
                )
                cache.set(messages, requested_model, result, body)
                return result

            except httpx.HTTPStatusError as e:
                last_error = str(e)
                status = e.response.status_code if e.response else 0

                if status == 429:
                    # Rate limited: respect Retry-After header, then retry same provider
                    retry_after = float(e.response.headers.get("Retry-After", 2 ** retry_idx))
                    wait_time = min(retry_after, 30)  # cap at 30s
                    log.warning(
                        f"429 Rate limited by {provider['id']} "
                        f"(retry {retry_idx + 1}/{max_retries_per_provider}), "
                        f"waiting {wait_time:.1f}s (Retry-After header)"
                    )
                    if retry_idx < max_retries_per_provider - 1:
                        await asyncio.sleep(wait_time)
                        continue  # retry same provider
                    else:
                        log.warning(f"429 max retries reached for {provider['id']}, switching provider")
                        break  # move to next provider

                elif status in (500, 502, 503, 504):
                    # Server error: retry with exponential backoff (1s, 2s, 4s)
                    delay = min(2 ** retry_idx, 8)  # 1s, 2s, 4s, cap 8s
                    log.warning(
                        f"{status} Server error from {provider['id']} "
                        f"(retry {retry_idx + 1}/{max_retries_per_provider}), "
                        f"waiting {delay}s"
                    )
                    manager.report_error(provider["id"], last_error)
                    if retry_idx < max_retries_per_provider - 1:
                        await asyncio.sleep(delay)
                        continue
                    else:
                        manager.stats.record(
                            provider["id"], model.get("id", "?"), 0, 0, 0, False, last_error
                        )
                        break  # move to next provider

                else:
                    # Client error (400, 401, 403, etc.) — don't retry, switch provider
                    log.error(f"{status} Client error from {provider['id']}: {last_error}")
                    manager.report_error(provider["id"], last_error)
                    manager.stats.record(
                        provider["id"], model.get("id", "?"), 0, 0, 0, False, last_error
                    )
                    break  # move to next provider

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                last_error = f"Timeout: {e}"
                delay = min(2 ** retry_idx, 8)
                log.warning(
                    f"Timeout from {provider['id']} "
                    f"(retry {retry_idx + 1}/{max_retries_per_provider}), "
                    f"waiting {delay}s"
                )
                manager.report_error(provider["id"], last_error)
                if retry_idx < max_retries_per_provider - 1:
                    await asyncio.sleep(delay)
                    continue
                else:
                    manager.stats.record(
                        provider["id"], model.get("id", "?"), 0, 0, 0, False, last_error
                    )
                    break  # move to next provider

            except Exception as e:
                last_error = str(e)
                log.error(f"Error from {provider['id']}: {last_error}")
                manager.report_error(provider["id"], last_error)
                manager.stats.record(
                    provider["id"], model.get("id", "?"), 0, 0, 0, False, last_error
                )
                break  # move to next provider (non-retryable error)

    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "message": f"ทุก provider ล้มเหลว ({len(tried_providers)} ตัว): {last_error or 'no providers available'}",
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
    for _attempt in range(3):
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

    timeout = manager.config.get("timeout", 30)
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
    # Request usage in final chunk (supported by OpenAI-compatible providers)
    payload["stream_options"] = {"include_usage": True}

    start_time = time.time()
    full_response = ""
    usage_from_stream = None

    try:
        stream_timeout = manager.config.get("stream_timeout", 60)
        async with httpx.AsyncClient(timeout=stream_timeout) as client:
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
                            # Capture usage from final chunk if available
                            if chunk.get("usage"):
                                usage_from_stream = chunk["usage"]
                            if chunk.get("choices"):
                                delta = chunk["choices"][0].get("delta", {})
                                full_response += delta.get("content", "")
                            # Don't forward stream_options chunk noise
                            if not chunk.get("choices") and not chunk.get("usage"):
                                yield f"data: {data}\n\n"
                                continue
                            yield f"data: {data}\n\n"
                        except json.JSONDecodeError:
                            continue

        latency = int((time.time() - start_time) * 1000)
        manager.report_success(provider["id"])

        # Use actual usage if available, otherwise estimate
        if usage_from_stream:
            tokens_in = usage_from_stream.get("prompt_tokens", 0)
            tokens_out = usage_from_stream.get("completion_tokens", 0)
        else:
            # Estimate: ~4 chars per token (conservative)
            prompt_text = json.dumps(messages, ensure_ascii=False)
            tokens_in = len(prompt_text) // 4
            tokens_out = len(full_response) // 4

        cost = manager.calc_cost(provider["id"], model["id"], tokens_in, tokens_out)
        manager.stats.record(provider["id"], model["id"], tokens_in, tokens_out, latency, True, cost_usd=cost)

    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response else 0
        log.warning(f"Stream HTTP {status} from {provider['id']}: {e}")
        manager.report_error(provider["id"], str(e))
        manager.stats.record(provider["id"], model["id"], 0, 0, 0, False, str(e))
        if status == 429:
            error_msg = f"Rate limited by {provider['id']}. Retry-After: {e.response.headers.get('Retry-After', '?')}s"
        else:
            error_msg = str(e)
        error_chunk = {"error": {"message": error_msg, "type": "stream_error", "code": status}}
        yield f"data: {json.dumps(error_chunk)}\n\n"

    except Exception as e:
        log.warning(f"Stream error from {provider['id']}: {e}")
        manager.report_error(provider["id"], str(e))
        manager.stats.record(provider["id"], model["id"], 0, 0, 0, False, str(e))
        error_chunk = {"error": {"message": str(e), "type": "stream_error"}}
        yield f"data: {json.dumps(error_chunk)}\n\n"


async def _stream_with_failover(provider, model, body, api_key, messages, requested_model, fallback_providers):
    """Stream with automatic failover to next provider on error."""
    try:
        async for chunk in _stream_request(provider, model, body, api_key, messages, requested_model):
            yield chunk
        return  # Stream succeeded
    except Exception as e:
        log.warning(f"Stream failover from {provider['id']}: {e}")

    # Try fallback providers
    for fb_provider in fallback_providers:
        fb_model = fb_provider["models"][0] if fb_provider.get("models") else None
        if not fb_model:
            continue
        fb_key = manager.get_api_key(fb_provider["id"])
        if not fb_key:
            continue
        log.info(f"Stream failover: trying {fb_provider['id']}")
        try:
            async for chunk in _stream_request(fb_provider, fb_model, body, fb_key, messages, requested_model):
                yield chunk
            return  # Fallback succeeded
        except Exception as e2:
            log.warning(f"Stream failover {fb_provider['id']} also failed: {e2}")
            continue

    # All providers failed
    error_chunk = {"error": {"message": "All providers failed for streaming", "type": "provider_exhausted"}}
    yield f"data: {json.dumps(error_chunk)}\n\n"
    yield "data: [DONE]\n\n"


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
    rate_limiter.configure(manager.config.get("rate_limit_rpm", 0), manager.config.get("rate_limit_rpm_per_key", 0))

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
    """
    Save API keys with proper change detection.

    Protocol (per field):
      - Field absent from payload → untouched (preserve existing)
      - Field value == current masked key → untouched
      - Field value is empty string "" → delete existing key
      - Field value is anything else → overwrite with new key
    """
    data = await request.json()
    masked_keys = key_store.get_masked_keys()
    to_save = {}
    for k, v in data.items():
        v = v.strip()
        if not v:
            # Empty → user wants to delete this key
            to_save[k] = ""
        elif v == masked_keys.get(k):
            # Matches masked display → user didn't change it, skip
            continue
        else:
            # New value → overwrite
            to_save[k] = v
    if to_save:
        manager.save_api_keys(to_save)
        manager.reload()
    return {"status": "ok", "message": "บันทึก API Key เรียบร้อย ✅"}


@app.get("/api/keys/masked")
async def api_masked_keys():
    """Return masked API keys for safe display in Dashboard."""
    masked = key_store.get_masked_keys()
    env_masked = {}
    for _pid, provider in manager.providers.items():
        env_key = provider.get("api_key_env")
        if env_key:
            # Check env var too
            env_val = os.environ.get(env_key)
            if env_val and env_key not in masked:
                env_masked[env_key] = mask_key(env_val)
    return {"keys": {**masked, **env_masked}, "encrypted": key_store.is_encrypted()}


@app.get("/api/keys/plain")
async def api_plain_keys():
    """Return decrypted API keys for display (toggle visibility). Requires dashboard auth."""
    keys = key_store.load_keys()
    env_keys = {}
    for _pid, provider in manager.providers.items():
        env_key = provider.get("api_key_env")
        if env_key and env_key not in keys:
            env_val = os.environ.get(env_key)
            if env_val:
                env_keys[env_key] = env_val
    return {"keys": {**keys, **env_keys}}


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
    rate_limiter.configure(manager.config.get("rate_limit_rpm", 0), manager.config.get("rate_limit_rpm_per_key", 0))
    return {"status": "ok", "message": "บันทึกการตั้งค่าเรียบร้อย ✅"}


@app.post("/api/cache/clear")
async def api_cache_clear():
    cache.clear()
    return {"status": "ok", "message": "ล้าง cache เรียบร้อย ✅"}


@app.get("/api/cache/stats")
async def api_cache_stats():
    return cache.get_stats()


# ── Custom Provider Management ──────────────────────
@app.get("/api/providers/custom")
async def api_get_custom_providers():
    """List user-added custom providers."""
    custom = load_custom_providers()
    result = []
    for pid, pdata in custom.items():
        env_key = pdata.get("api_key_env")
        has_key = bool(env_key and (manager.api_keys.get(env_key) or os.environ.get(env_key))) if env_key else True
        result.append({
            "id": pid,
            "name": pdata.get("name", pid),
            "api_base": pdata.get("api_base", ""),
            "has_key": has_key,
            "models": pdata.get("models", []),
            "speed": pdata.get("speed", ""),
            "signup_url": pdata.get("signup_url", ""),
            "desc": pdata.get("desc", ""),
            "flag": pdata.get("flag", "🌐"),
            "custom": True,
        })
    return {"providers": result}


@app.post("/api/providers/custom")
async def api_add_custom_provider(request: Request):
    """Add or update a custom provider."""
    data = await request.json()
    pid = data.get("id", "").strip().lower().replace(" ", "-")
    if not pid:
        return JSONResponse(status_code=400, content={"error": "ต้องใส่ Provider ID"})

    # Validate required fields
    api_base = data.get("api_base", "").strip().rstrip("/")
    if not api_base:
        return JSONResponse(status_code=400, content={"error": "ต้องใส่ API Base URL"})

    models = data.get("models", [])
    if not models:
        return JSONResponse(status_code=400, content={"error": "ต้องใส่อย่างน้อย 1 โมเดล"})

    # Build provider config
    api_key_env = data.get("api_key_env", f"CUSTOM_{pid.upper()}_API_KEY")
    provider_config = {
        "name": data.get("name", pid),
        "api_base": api_base,
        "api_key_env": api_key_env if data.get("needs_key", True) else None,
        "models": [
            {
                "id": m.get("id", m) if isinstance(m, dict) else m,
                "context": m.get("context", 4096) if isinstance(m, dict) else 4096,
                "free": m.get("free", False) if isinstance(m, dict) else False,
                "priority": m.get("priority", 50) if isinstance(m, dict) else 50,
                "desc": m.get("desc", "") if isinstance(m, dict) else "",
            }
            for m in models
        ],
        "speed": data.get("speed", "⚡⚡⚡"),
        "signup_url": data.get("signup_url", ""),
        "desc": data.get("desc", ""),
        "flag": data.get("flag", "🌐"),
        "custom": True,
    }

    custom = load_custom_providers()
    custom[pid] = provider_config
    save_custom_providers(custom)
    manager.reload()

    return {"status": "ok", "message": f"เพิ่ม Provider '{provider_config['name']}' สำเร็จ ✅", "id": pid}


@app.delete("/api/providers/custom/{provider_id}")
async def api_delete_custom_provider(provider_id: str):
    """Delete a custom provider."""
    custom = load_custom_providers()
    if provider_id not in custom:
        return JSONResponse(status_code=404, content={"error": "ไม่พบ custom provider นี้"})

    name = custom[provider_id].get("name", provider_id)
    del custom[provider_id]
    save_custom_providers(custom)
    manager.reload()

    return {"status": "ok", "message": f"ลบ Provider '{name}' สำเร็จ 🗑️"}


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


@app.get("/api/stats/latency")
async def api_latency_stats(days: int = 7):
    """Per-provider latency stats for smart routing decisions."""
    manager.stats._ensure_conn()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with manager.stats._lock:
        cur = manager.stats._conn.execute(
            "SELECT provider, "
            "AVG(latency_ms) as avg_ms, "
            "MIN(latency_ms) as min_ms, "
            "MAX(latency_ms) as max_ms, "
            "COUNT(*) as total, "
            "SUM(success) as successes, "
            "SUM(CASE WHEN latency_ms < 1000 THEN 1 ELSE 0 END) as fast_count "
            "FROM requests WHERE ts > ? GROUP BY provider ORDER BY avg_ms",
            (cutoff,),
        )
        results = []
        for row in cur.fetchall():
            total = row[4] or 1
            results.append({
                "provider": row[0],
                "avg_latency_ms": round(row[1] or 0),
                "min_latency_ms": row[2] or 0,
                "max_latency_ms": row[3] or 0,
                "total_requests": total,
                "success_rate": round((row[5] or 0) / total * 100, 1),
                "fast_rate": round((row[6] or 0) / total * 100, 1),
            })
    return {"period_days": days, "providers": results}


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
        "cache": cache.get_stats() if cache._enabled else {"enabled": False},
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


# ── Auth Endpoints ──────────────────────────────────
@app.post("/api/auth/login")
async def api_login(request: Request):
    """Login with dashboard password. Returns session token."""
    if not DASHBOARD_AUTH_ENABLED:
        return {"status": "ok", "message": "Auth not enabled", "token": ""}

    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Request must be JSON"})

    password = data.get("password", "")
    if not password:
        return JSONResponse(status_code=400, content={"error": "กรุณาใส่รหัสผ่าน"})

    if not secrets.compare_digest(password.encode(), DASHBOARD_PASSWORD.encode()):
        return JSONResponse(status_code=401, content={"error": "รหัสผ่านไม่ถูกต้อง"})

    token = session_manager.create()
    resp = JSONResponse(content={"status": "ok", "message": "เข้าสู่ระบบสำเร็จ ✅", "token": token})
    resp.set_cookie(
        key="routerai_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,  # 24h
        secure=False,  # Set True behind HTTPS
    )
    return resp


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    """Logout — revoke session token."""
    token = _extract_session_token(request)
    if token:
        session_manager.revoke(token)
    resp = JSONResponse(content={"status": "ok", "message": "ออกจากระบบแล้ว"})
    resp.delete_cookie("routerai_session")
    return resp


@app.get("/api/auth/status")
async def api_auth_status():
    """Check if dashboard auth is enabled."""
    return {
        "auth_enabled": DASHBOARD_AUTH_ENABLED,
        "cors_origins": CORS_ORIGINS,
    }


# ── Health Check ────────────────────────────────────
@app.get("/health")
async def health(deep: bool = False):
    """Health check endpoint. Pass ?deep=true to ping each provider."""
    available = manager.get_available_providers()
    provider_status = {}

    if deep:
        # Actually ping each available provider's API base
        client = get_http_client(timeout=5)
        for p in available:
            try:
                resp = client.get(p["api_base"].rsplit("/v1", 1)[0], timeout=5)
                provider_status[p["id"]] = {"reachable": True, "status_code": resp.status_code}
            except Exception as e:
                provider_status[p["id"]] = {"reachable": False, "error": str(e)[:100]}
    else:
        for p in available:
            cooldown = manager._cooldown_until.get(p["id"], 0)
            provider_status[p["id"]] = {
                "available": True,
                "in_cooldown": time.time() < cooldown,
                "error_count": manager._error_counts.get(p["id"], 0),
            }

    budget_exceeded, budget_spent, budget_limit = manager.check_budget()
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "providers_available": len(available),
        "providers_total": len(manager.providers),
        "provider_status": provider_status,
        "budget": {
            "daily_limit_usd": budget_limit,
            "spent_today_usd": budget_spent,
            "exceeded": budget_exceeded,
        } if budget_limit > 0 else None,
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
