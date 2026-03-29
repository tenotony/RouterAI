"""
RouterAI Tests — Core functionality tests
"""
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ── Test: Config Loading ────────────────────────────

class TestConfigLoading:
    """Test configuration file loading."""

    def test_load_proxy_config_defaults(self, tmp_path):
        """Default config should have all required keys."""
        from server import load_proxy_config
        # Patch the config file path to non-existent
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
        """Config should load from existing file."""
        from server import load_proxy_config
        config_file = tmp_path / "proxy_config.json"
        config_data = {"prefer_free": False, "cache_ttl": 7200, "timeout": 30}
        config_file.write_text(json.dumps(config_data))

        with patch("server.PROXY_CONFIG_FILE", config_file):
            cfg = load_proxy_config()
        assert cfg["prefer_free"] is False
        assert cfg["cache_ttl"] == 7200
        assert cfg["timeout"] == 30
        # Should still have defaults for unset keys
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
        import time
        rl = RateLimiter()
        rl.configure(60)  # 60 RPM = 1/sec
        # Should allow first few requests
        assert rl.is_allowed("1.2.3.4") is True
        assert rl.is_allowed("1.2.3.4") is True

    def test_separate_clients(self):
        from server import RateLimiter
        rl = RateLimiter()
        rl.configure(60)
        # Each client should have separate limits
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
        import time
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


# ── Test: Flask App Endpoints ───────────────────────

class TestFlaskApp:
    """Test Flask API endpoints."""

    def _get_client(self, tmp_path):
        """Create a test client."""
        with patch("server.DATA_DIR", tmp_path), \
             patch("server.CACHE_DIR", tmp_path / "cache"), \
             patch("server.STATS_FILE", tmp_path / "stats.json"), \
             patch("server.PROVIDERS_FILE", tmp_path / "providers.json"), \
             patch("server.API_KEYS_FILE", tmp_path / "api_keys.json"):
            # Create empty providers file
            (tmp_path / "providers.json").write_text("{}")
            from server import app
            app.config["TESTING"] = True
            return app.test_client()

    def test_health_endpoint(self, tmp_path):
        client = self._get_client(tmp_path)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json
        assert data["status"] == "healthy"
        assert "version" in data

    def test_dashboard_index(self, tmp_path):
        client = self._get_client(tmp_path)
        resp = client.get("/")
        # Should serve the dashboard HTML (or 404 if web dir missing)
        assert resp.status_code in (200, 404)

    def test_api_providers_empty(self, tmp_path):
        client = self._get_client(tmp_path)
        resp = client.get("/api/providers")
        assert resp.status_code == 200
        data = resp.json
        assert "providers" in data

    def test_api_config_get(self, tmp_path):
        client = self._get_client(tmp_path)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json
        assert "prefer_free" in data

    def test_api_config_post(self, tmp_path):
        client = self._get_client(tmp_path)
        resp = client.post("/api/config", json={"timeout": 30})
        assert resp.status_code == 200

    def test_api_cache_stats(self, tmp_path):
        client = self._get_client(tmp_path)
        resp = client.get("/api/cache/stats")
        assert resp.status_code == 200
        data = resp.json
        assert "entries" in data

    def test_api_cache_clear(self, tmp_path):
        client = self._get_client(tmp_path)
        resp = client.post("/api/cache/clear")
        assert resp.status_code == 200

    def test_v1_models_no_providers(self, tmp_path):
        client = self._get_client(tmp_path)
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json
        assert data["object"] == "list"

    def test_chat_completions_no_providers(self, tmp_path):
        client = self._get_client(tmp_path)
        resp = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hello"}],
            "model": "test"
        })
        # Should return 503 when no providers available
        assert resp.status_code == 503

    def test_chat_completions_missing_messages(self, tmp_path):
        client = self._get_client(tmp_path)
        resp = client.post("/v1/chat/completions", json={"model": "test"})
        assert resp.status_code == 400


# ── Test: Auth ──────────────────────────────────────

class TestAuth:
    """Test API authentication."""

    def test_no_auth_when_key_not_set(self, tmp_path):
        """Should allow access when ROUTERAI_API_KEY is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove ROUTERAI_API_KEY if present
            os.environ.pop("ROUTERAI_API_KEY", None)
            from server import _check_auth
            # In a request context
            with patch("server.ROUTERAI_API_KEY", ""):
                assert _check_auth() is True


# ── Test: Provider Manager ──────────────────────────

class TestProviderManager:
    """Test provider management."""

    def test_exponential_backoff(self, tmp_path):
        """Error cooldown should increase exponentially."""
        with patch("server.PROVIDERS_FILE", tmp_path / "providers.json"), \
             patch("server.API_KEYS_FILE", tmp_path / "api_keys.json"), \
             patch("server.PROXY_CONFIG_FILE", tmp_path / "proxy_config.json"), \
             patch("server.DATA_DIR", tmp_path), \
             patch("server.CACHE_DIR", tmp_path / "cache"), \
             patch("server.STATS_FILE", tmp_path / "stats.json"):
            (tmp_path / "providers.json").write_text("{}")
            from server import ProviderManager
            pm = ProviderManager()

            # First 2 errors: no cooldown
            pm.report_error("test", "error1")
            pm.report_error("test", "error2")
            assert pm._cooldown_until["test"] == 0

            # 3rd error: should trigger cooldown
            pm.report_error("test", "error3")
            assert pm._cooldown_until["test"] > 0

            # Success resets
            pm.report_success("test")
            assert pm._error_counts["test"] == 0
