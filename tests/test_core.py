"""
RouterAI Tests — Core functionality tests (FastAPI + SQLite)
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

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


# ── Test: API Key Management ────────────────────────

class TestAPIKeyManagement:
    """Test API key CRUD: save, overwrite, delete, masked/plain endpoints."""

    def test_save_key(self, client):
        """POST /api/keys with new key should save it."""
        resp = client.post("/api/keys", json={"TEST_API_KEY": "sk-test123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

        # Verify via masked endpoint
        resp = client.get("/api/keys/masked")
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert "TEST_API_KEY" in keys
        assert keys["TEST_API_KEY"].endswith("t123")  # masked: sk-...t123
        assert "..." in keys["TEST_API_KEY"]

    def test_overwrite_key(self, client):
        """POST /api/keys with same key name should overwrite."""
        # Save first key
        client.post("/api/keys", json={"TEST_API_KEY": "sk-old-key-1111"})
        # Overwrite with new key
        resp = client.post("/api/keys", json={"TEST_API_KEY": "sk-new-key-2222"})
        assert resp.status_code == 200

        # Verify new key is in effect via plain endpoint
        resp = client.get("/api/keys/plain")
        keys = resp.json()["keys"]
        assert keys["TEST_API_KEY"] == "sk-new-key-2222"

    def test_delete_key_by_empty_value(self, client):
        """POST /api/keys with empty value should delete the key."""
        # Save key first
        client.post("/api/keys", json={"TEST_DELETE_KEY": "sk-delete-me"})
        # Verify it exists
        resp = client.get("/api/keys/plain")
        assert "TEST_DELETE_KEY" in resp.json()["keys"]

        # Delete by sending empty string
        resp = client.post("/api/keys", json={"TEST_DELETE_KEY": ""})
        assert resp.status_code == 200

        # Verify deletion
        resp = client.get("/api/keys/plain")
        assert "TEST_DELETE_KEY" not in resp.json()["keys"]

    def test_masked_value_skips_update(self, client):
        """POST /api/keys with masked value should NOT overwrite existing key."""
        # Save a key
        client.post("/api/keys", json={"TEST_KEEP_KEY": "sk-real-secret-key"})
        # Get its masked form
        resp = client.get("/api/keys/masked")
        masked = resp.json()["keys"]["TEST_KEEP_KEY"]

        # Send the masked value back (user didn't change it)
        resp = client.post("/api/keys", json={"TEST_KEEP_KEY": masked})
        assert resp.status_code == 200

        # Verify original key is preserved (not replaced with masked string)
        resp = client.get("/api/keys/plain")
        assert resp.json()["keys"]["TEST_KEEP_KEY"] == "sk-real-secret-key"

    def test_plain_endpoint(self, client):
        """GET /api/keys/plain should return decrypted keys."""
        client.post("/api/keys", json={"PLAIN_TEST": "sk-plaintext-value"})
        resp = client.get("/api/keys/plain")
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert keys["PLAIN_TEST"] == "sk-plaintext-value"

    def test_multiple_keys_independent(self, client):
        """Saving one key should not affect other keys."""
        client.post("/api/keys", json={"KEY_A": "sk-aaa", "KEY_B": "sk-bbb"})
        # Delete only KEY_A
        client.post("/api/keys", json={"KEY_A": ""})
        # KEY_B should still exist
        resp = client.get("/api/keys/plain")
        keys = resp.json()["keys"]
        assert "KEY_A" not in keys
        assert keys["KEY_B"] == "sk-bbb"

    def test_untouched_fields_preserved(self, client):
        """Fields not included in POST should remain unchanged."""
        client.post("/api/keys", json={"KEY_X": "sk-xxx", "KEY_Y": "sk-yyy"})
        # Update only KEY_X, don't send KEY_Y at all
        client.post("/api/keys", json={"KEY_X": "sk-xxx-new"})
        # KEY_Y should still be there
        resp = client.get("/api/keys/plain")
        keys = resp.json()["keys"]
        assert keys["KEY_X"] == "sk-xxx-new"
        assert keys["KEY_Y"] == "sk-yyy"

    def test_send_masked_preserves_key(self, client):
        """Sending masked value back should NOT overwrite the real key."""
        # Save key
        client.post("/api/keys", json={"MY_KEY": "sk-super-secret-value"})
        # Get masked
        resp = client.get("/api/keys/masked")
        masked = resp.json()["keys"]["MY_KEY"]
        assert "..." in masked

        # Send masked value back (frontend simulating untouched field)
        client.post("/api/keys", json={"OTHER_KEY": "sk-new", "MY_KEY": masked})
        # MY_KEY should still be original value
        resp = client.get("/api/keys/plain")
        keys = resp.json()["keys"]
        assert keys["MY_KEY"] == "sk-super-secret-value"
        assert keys["OTHER_KEY"] == "sk-new"

    def test_delete_does_not_affect_other_keys(self, client):
        """Deleting one key must not touch other keys."""
        client.post("/api/keys", json={
            "KEY_A": "sk-aaa-1111",
            "KEY_B": "sk-bbb-2222",
            "KEY_C": "sk-ccc-3333"
        })
        # Delete KEY_B only
        resp = client.post("/api/keys", json={"KEY_B": ""})
        assert resp.status_code == 200

        resp = client.get("/api/keys/plain")
        keys = resp.json()["keys"]
        assert "KEY_B" not in keys
        assert keys["KEY_A"] == "sk-aaa-1111"
        assert keys["KEY_C"] == "sk-ccc-3333"

    def test_overwrite_with_new_key(self, client):
        """Sending a new value should overwrite existing key."""
        client.post("/api/keys", json={"MY_KEY": "sk-old-value"})
        client.post("/api/keys", json={"MY_KEY": "sk-brand-new-value"})
        resp = client.get("/api/keys/plain")
        assert resp.json()["keys"]["MY_KEY"] == "sk-brand-new-value"

    def test_delete_key_then_re_add(self, client):
        """After deleting a key, adding it again should work."""
        client.post("/api/keys", json={"TEMP_KEY": "sk-first"})
        client.post("/api/keys", json={"TEMP_KEY": ""})
        resp = client.get("/api/keys/plain")
        assert "TEMP_KEY" not in resp.json()["keys"]

        client.post("/api/keys", json={"TEMP_KEY": "sk-second"})
        resp = client.get("/api/keys/plain")
        assert resp.json()["keys"]["TEMP_KEY"] == "sk-second"

    def test_empty_body_changes_nothing(self, client):
        """Sending empty JSON body should not modify any keys."""
        client.post("/api/keys", json={"KEEP_ME": "sk-preserved"})
        client.post("/api/keys", json={})
        resp = client.get("/api/keys/plain")
        assert resp.json()["keys"]["KEEP_ME"] == "sk-preserved"

    def test_mixed_edit_preserve_delete(self, client):
        """Simulate: edit A, preserve B, delete C in one save."""
        client.post("/api/keys", json={
            "KEY_A": "sk-aaa",
            "KEY_B": "sk-bbb",
            "KEY_C": "sk-ccc"
        })
        # Get masked for KEY_B (simulate frontend sending masked for untouched)
        masked = client.get("/api/keys/masked").json()["keys"]["KEY_B"]
        # Edit A, preserve B (masked), delete C (empty)
        client.post("/api/keys", json={
            "KEY_A": "sk-aaa-edited",
            "KEY_B": masked,
            "KEY_C": ""
        })
        resp = client.get("/api/keys/plain")
        keys = resp.json()["keys"]
        assert keys["KEY_A"] == "sk-aaa-edited"
        assert keys["KEY_B"] == "sk-bbb"
        assert "KEY_C" not in keys


# ── Test: Legacy File Migration ─────────────────────

class TestLegacyMigration:
    """Test migration from legacy file paths to DATA_DIR."""

    def test_migration_copies_file(self, tmp_path):
        """Legacy file should be copied to DATA_DIR if new path doesn't exist."""
        from server import _migrate_legacy_file

        legacy = tmp_path / "old_keys.json"
        legacy.write_text('{"test": "value"}')
        new_path = tmp_path / "data" / "new_keys.json"

        _migrate_legacy_file(legacy, new_path)
        assert new_path.exists()
        assert new_path.read_text() == '{"test": "value"}'

    def test_migration_does_not_overwrite(self, tmp_path):
        """Migration should NOT overwrite existing files in DATA_DIR."""
        from server import _migrate_legacy_file

        legacy = tmp_path / "old.json"
        legacy.write_text('{"old": true}')
        new_path = tmp_path / "data" / "new.json"
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text('{"existing": true}')

        _migrate_legacy_file(legacy, new_path)
        # Should keep existing, not overwrite
        assert '"existing": true' in new_path.read_text()

    def test_migration_skips_missing_legacy(self, tmp_path):
        """Migration should be a no-op if legacy file doesn't exist."""
        from server import _migrate_legacy_file

        legacy = tmp_path / "nonexistent.json"
        new_path = tmp_path / "data" / "new.json"

        _migrate_legacy_file(legacy, new_path)
        assert not new_path.exists()


# ── Test: Task Type Detection ───────────────────────

class TestTaskTypeDetection:
    """Test smart routing task type detection."""

    def test_detects_coding_task(self):
        from server import ProviderManager
        assert ProviderManager.detect_task_type(
            [{"role": "user", "content": "Write a Python function to sort a list"}]
        ) == "coding"
        assert ProviderManager.detect_task_type(
            [{"role": "user", "content": "ช่วยเขียนโค้ด Python หน่อย"}]
        ) == "coding"
        assert ProviderManager.detect_task_type(
            [{"role": "user", "content": "Debug this JavaScript code"}]
        ) == "coding"

    def test_detects_creative_task(self):
        from server import ProviderManager
        assert ProviderManager.detect_task_type(
            [{"role": "user", "content": "Write a story about a dragon"}]
        ) == "creative"
        assert ProviderManager.detect_task_type(
            [{"role": "user", "content": "แต่งกลอนวันแม่ให้หน่อย"}]
        ) == "creative"

    def test_detects_general_task(self):
        from server import ProviderManager
        assert ProviderManager.detect_task_type(
            [{"role": "user", "content": "What is the capital of France?"}]
        ) == "general"
        assert ProviderManager.detect_task_type(
            [{"role": "user", "content": "Translate hello to Thai"}]
        ) == "general"

    def test_empty_messages_returns_general(self):
        from server import ProviderManager
        assert ProviderManager.detect_task_type([]) == "general"

    def test_multimodal_content(self):
        from server import ProviderManager
        assert ProviderManager.detect_task_type(
            [{"role": "user", "content": [
                {"type": "text", "text": "Write a poem about this image"},
                {"type": "image_url", "image_url": {"url": "data:..."}}
            ]}]
        ) == "creative"


# ── Test: Cost Graph Endpoint ──────────────────────

class TestCostGraph:
    """Test cost graph API endpoint."""

    def test_cost_graph_empty(self, client):
        resp = client.get("/api/stats/cost-graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "daily" in data
        assert "by_provider" in data
        assert "total_cost_usd" in data
        assert "period_days" in data

    def test_cost_graph_with_data(self, tmp_path):
        from server import StatsDB
        from unittest.mock import patch
        with patch("server.DATA_DIR", tmp_path), \
             patch("server.STATS_DB", tmp_path / "stats.db"):
            stats = StatsDB()
            stats.record("groq", "llama-3.3-70b-versatile", 100, 200, 500, True, cost_usd=0.001)
            stats.record("google", "gemini-2.0-flash", 200, 300, 300, True, cost_usd=0.002)
            result = stats.get_cost_graph(days=7)
            assert result["total_cost_usd"] >= 0.003
            assert len(result["daily"]) >= 1
            assert len(result["by_provider"]) >= 1


# ── Test: Pydantic Config Validation ───────────────

class TestPydanticValidation:
    """Test config validation with Pydantic."""

    def test_valid_config(self):
        from server import HAS_PYDANTIC
        if not HAS_PYDANTIC:
            pytest.skip("pydantic not installed")
        from server import ProxyConfigModel
        cfg = ProxyConfigModel(prefer_free=True, cache_ttl=3600)
        assert cfg.cache_ttl == 3600

    def test_invalid_cache_ttl(self):
        from server import HAS_PYDANTIC
        if not HAS_PYDANTIC:
            pytest.skip("pydantic not installed")
        from server import ProxyConfigModel
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ProxyConfigModel(cache_ttl=10)  # Too low (min 60)

    def test_invalid_budget_action(self):
        from server import HAS_PYDANTIC
        if not HAS_PYDANTIC:
            pytest.skip("pydantic not installed")
        from server import ProxyConfigModel
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ProxyConfigModel(budget_action="invalid")


# ── Test: Structured Logging ────────────────────────

class TestStructuredLogging:
    """Test JSON structured logging formatter."""

    def test_json_formatter_output(self):
        import logging
        from server import _JsonFormatter
        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "info"
        assert parsed["msg"] == "test message"
        assert parsed["logger"] == "test"
        assert "ts" in parsed
