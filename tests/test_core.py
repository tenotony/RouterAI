"""
RouterAI Tests — Core functionality tests (FastAPI + SQLite)
"""
import os
import sys
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ── Test: Config Loading ────────────────────────────

class TestConfigLoading:
    """Test configuration file loading."""

    def test_load_proxy_config_defaults(self, tmp_path):
        from server import load_proxy_config
        with patch("server.PROXY_CONFIG_FILE", tmp_path / "nonexistent.json"):
            cfg = load_proxy_config()
        assert "prefer_free" in cfg
        assert "auto_failover" in cfg
        assert "cache_enabled" in cfg
        assert "cache_ttl" in cfg
        assert "max_retries" in cfg
        assert "timeout" in cfg
        assert "rate_limit_rpm" in cfg

    def test_load_proxy_config_from_file(self, tmp_path):
        from server import load_proxy_config
        config_file = tmp_path / "proxy_config.json"
        config_data = {"prefer_free": False, "cache_ttl": 7200, "timeout": 30}
        config_file.write_text(json.dumps(config_data))

        with patch("server.PROXY_CONFIG_FILE", config_file):
            cfg = load_proxy_config()
        assert cfg["prefer_free"] is False
        assert cfg["cache_ttl"] == 7200
        assert cfg["timeout"] == 30
        assert "auto_failover" in cfg


# ── Test: Rate Limiter ──────────────────────────────

class TestRateLimiter:
    """Test rate limiting logic."""

    def test_disabled_when_rpm_zero(self):
        from server import RateLimiter
        rl = RateLimiter()
        rl.configure(0)
        assert rl.is_allowed("1.2.3.4") is True
        assert rl.is_allowed("1.2.3.4") is True

    def test_allows_within_limit(self):
        from server import RateLimiter
        rl = RateLimiter()
        rl.configure(60)
        assert rl.is_allowed("1.2.3.4") is True
        assert rl.is_allowed("1.2.3.4") is True

    def test_separate_clients(self):
        from server import RateLimiter
        rl = RateLimiter()
        rl.configure(60)
        assert rl.is_allowed("1.1.1.1") is True
        assert rl.is_allowed("2.2.2.2") is True

    def test_wait_time_zero_when_disabled(self):
        from server import RateLimiter
        rl = RateLimiter()
        rl.configure(0)
        assert rl.get_wait_time("1.2.3.4") == 0


# ── Test: Response Cache ────────────────────────────

class TestResponseCache:
    """Test caching system."""

    def test_get_miss(self, tmp_path):
        from server import ResponseCache
        with patch("server.CACHE_DIR", tmp_path):
            cache = ResponseCache()
            result = cache.get([{"role": "user", "content": "hello"}], "test-model")
        assert result is None

    def test_set_and_get(self, tmp_path):
        from server import ResponseCache
        with patch("server.CACHE_DIR", tmp_path):
            cache = ResponseCache()
            messages = [{"role": "user", "content": "hello"}]
            model = "test-model"
            response = {"choices": [{"message": {"content": "hi"}}]}

            cache.set(messages, model, response)
            result = cache.get(messages, model)
        assert result == response

    def test_cache_disabled(self, tmp_path):
        from server import ResponseCache
        with patch("server.CACHE_DIR", tmp_path):
            cache = ResponseCache()
            cache.update_config(enabled=False, ttl=3600)

            messages = [{"role": "user", "content": "hello"}]
            model = "test-model"
            response = {"choices": [{"message": {"content": "hi"}}]}

            cache.set(messages, model, response)
            result = cache.get(messages, model)
        assert result is None

    def test_cache_clear(self, tmp_path):
        from server import ResponseCache
        with patch("server.CACHE_DIR", tmp_path):
            cache = ResponseCache()
            messages = [{"role": "user", "content": "hello"}]
            response = {"choices": [{"message": {"content": "hi"}}]}
            cache.set(messages, "model", response)
            assert cache.get_stats()["entries"] == 1
            cache.clear()
            assert cache.get_stats()["entries"] == 0

    def test_cache_stats(self, tmp_path):
        from server import ResponseCache
        with patch("server.CACHE_DIR", tmp_path):
            cache = ResponseCache()
            stats = cache.get_stats()
        assert "entries" in stats
        assert "total_size_kb" in stats
        assert "enabled" in stats
        assert "ttl_seconds" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0

    def test_cache_hit_miss_tracking(self, tmp_path):
        from server import ResponseCache
        with patch("server.CACHE_DIR", tmp_path):
            cache = ResponseCache()
            messages = [{"role": "user", "content": "hello"}]
            model = "test-model"
            response = {"choices": [{"message": {"content": "hi"}}]}

            # Miss
            result = cache.get(messages, model)
            assert result is None
            stats = cache.get_stats()
            assert stats["misses"] == 1
            assert stats["hits"] == 0

            # Set and hit
            cache.set(messages, model, response)
            result = cache.get(messages, model)
            assert result == response
            stats = cache.get_stats()
            assert stats["hits"] == 1
            assert stats["misses"] == 1
            assert stats["hit_rate"] == 50.0


# ── Test: SQLite Stats ──────────────────────────────

class TestStatsDB:
    """Test SQLite statistics."""

    def test_record_and_summary(self, tmp_path):
        from server import StatsDB
        with patch("server.DATA_DIR", tmp_path), \
             patch("server.STATS_DB", tmp_path / "stats.db"):
            stats = StatsDB()
            stats.record("groq", "llama-3.3-70b-versatile", 100, 200, 500, True)
            stats.record("groq", "llama-3.3-70b-versatile", 100, 200, 300, True)
            stats.record("google", "gemini-2.0-flash", 100, 200, 400, False, "timeout")

            summary = stats.get_summary(days=7)
            assert summary["total_requests"] == 3
            assert summary["success_rate"] > 0
            assert summary["successful_requests"] == 2
            assert summary["failed_requests"] == 1
            assert "groq" in summary["by_provider"]
            assert "google" in summary["by_provider"]
            assert summary["by_provider"]["groq"]["count"] == 2
            # Daily breakdown should exist
            assert isinstance(summary["daily"], list)
            assert len(summary["daily"]) >= 1
            # Don't close() — avoids corrupting global manager.stats connection


# ── Test: FastAPI App Endpoints ─────────────────────

@pytest.fixture
def client(tmp_path):
    """Create a test client with isolated data dirs."""
    # Create minimal providers file
    providers_file = tmp_path / "providers.json"
    providers_file.write_text("{}")
    api_keys_file = tmp_path / "api_keys.json"
    api_keys_file.write_text("{}")
    config_file = tmp_path / "proxy_config.json"
    config_file.write_text("{}")

    with patch("server.PROVIDERS_FILE", providers_file), \
         patch("server.API_KEYS_FILE", api_keys_file), \
         patch("server.PROXY_CONFIG_FILE", config_file), \
         patch("server.DATA_DIR", tmp_path), \
         patch("server.CACHE_DIR", tmp_path / "cache"), \
         patch("server.STATS_DB", tmp_path / "stats.db"), \
         patch("server.ROUTERAI_API_KEY", ""):
        from server import app
        with TestClient(app) as c:
            yield c


class TestFastAPIEndpoints:
    """Test FastAPI endpoints."""

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_api_providers_empty(self, client):
        resp = client.get("/api/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data

    def test_api_config_get(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "prefer_free" in data

    def test_api_config_post(self, client):
        resp = client.post("/api/config", json={"timeout": 30})
        assert resp.status_code == 200

    def test_api_cache_stats(self, client):
        resp = client.get("/api/cache/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data

    def test_api_cache_clear(self, client):
        resp = client.post("/api/cache/clear")
        assert resp.status_code == 200

    def test_v1_models_no_providers(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"

    def test_chat_completions_no_providers(self, client):
        resp = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hello"}],
            "model": "test"
        })
        assert resp.status_code == 503

    def test_chat_completions_missing_messages(self, client):
        resp = client.post("/v1/chat/completions", json={"model": "test"})
        assert resp.status_code == 400

    def test_api_status(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert "stats" in data
        assert "cache" in data

    def test_openapi_docs_available(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200


# ── Test: Auth ──────────────────────────────────────

class TestAuth:
    """Test API authentication."""

    def test_no_auth_when_key_not_set(self, client):
        """Should allow access when ROUTERAI_API_KEY is not set."""
        resp = client.get("/v1/models")
        assert resp.status_code == 200

    def test_auth_required_when_key_set(self, tmp_path):
        """Should reject access when key is set but not provided."""
        providers_file = tmp_path / "providers.json"
        providers_file.write_text("{}")
        api_keys_file = tmp_path / "api_keys.json"
        api_keys_file.write_text("{}")

        with patch("server.PROVIDERS_FILE", providers_file), \
             patch("server.API_KEYS_FILE", api_keys_file), \
             patch("server.DATA_DIR", tmp_path), \
             patch("server.CACHE_DIR", tmp_path / "cache"), \
             patch("server.STATS_DB", tmp_path / "stats.db"), \
             patch("server.ROUTERAI_API_KEY", "test-secret-key"):
            from server import app
            with TestClient(app) as c:
                resp = c.get("/v1/models")
                assert resp.status_code == 401

                # With valid key
                resp = c.get("/v1/models", headers={"Authorization": "Bearer test-secret-key"})
                assert resp.status_code == 200


# ── Test: Custom Providers ──────────────────────────

class TestCustomProviders:
    """Test custom provider CRUD."""

    def test_get_custom_providers_empty(self, client):
        resp = client.get("/api/providers/custom")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data

    def test_add_custom_provider(self, client):
        resp = client.post("/api/providers/custom", json={
            "id": "test-provider",
            "name": "Test Provider",
            "api_base": "http://localhost:9999/v1",
            "models": [{"id": "test-model", "context": 4096, "free": True}],
            "desc": "Test",
            "flag": "🧪",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test-provider"

    def test_add_custom_provider_missing_fields(self, client):
        # Missing api_base
        resp = client.post("/api/providers/custom", json={
            "id": "bad",
            "name": "Bad",
            "models": [{"id": "m"}],
        })
        assert resp.status_code == 400

        # Missing models
        resp = client.post("/api/providers/custom", json={
            "id": "bad2",
            "name": "Bad2",
            "api_base": "http://localhost:9999/v1",
            "models": [],
        })
        assert resp.status_code == 400

    def test_delete_custom_provider(self, client):
        # Add first
        client.post("/api/providers/custom", json={
            "id": "to-delete",
            "name": "To Delete",
            "api_base": "http://localhost:9999/v1",
            "models": [{"id": "m"}],
        })
        # Delete
        resp = client.delete("/api/providers/custom/to-delete")
        assert resp.status_code == 200

    def test_delete_nonexistent_custom_provider(self, client):
        resp = client.delete("/api/providers/custom/nonexistent-xyz")
        assert resp.status_code == 404


# ── Test: Latency Stats ────────────────────────────

class TestLatencyStats:
    """Test latency statistics endpoint."""

    def test_latency_stats_empty(self, client):
        resp = client.get("/api/stats/latency")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        assert "period_days" in data


# ── Test: Provider Manager ──────────────────────────

class TestProviderManager:
    """Test provider management."""

    def test_exponential_backoff(self, tmp_path):
        with patch("server.PROVIDERS_FILE", tmp_path / "providers.json"), \
             patch("server.API_KEYS_FILE", tmp_path / "api_keys.json"), \
             patch("server.PROXY_CONFIG_FILE", tmp_path / "proxy_config.json"), \
             patch("server.DATA_DIR", tmp_path), \
             patch("server.CACHE_DIR", tmp_path / "cache"), \
             patch("server.STATS_DB", tmp_path / "stats.db"):
            (tmp_path / "providers.json").write_text("{}")
            from server import ProviderManager
            pm = ProviderManager()

            pm.report_error("test", "error1")
            pm.report_error("test", "error2")
            assert pm._cooldown_until["test"] == 0

            pm.report_error("test", "error3")
            assert pm._cooldown_until["test"] > 0

            pm.report_success("test")
            assert pm._error_counts["test"] == 0
