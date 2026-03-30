# RouterAI Bug Fixes

## Issues Found & Fixed

### 1. `_make_request` - Missing provider-specific headers
- OpenRouter requires `HTTP-Referer` header or returns 404
- Some providers need `X-Title` for identification
- Trailing slashes in `api_base` cause double-slash URLs

### 2. `api_test_provider` - No response validation
- Returns success even when API response contains `{"error": ...}`
- Should check for error field before reporting success

### 3. `chat_completions` - JSON error body not retried
- When provider returns HTTP 200 with error body, `raise Exception` falls to generic handler which `break`s immediately
- Should retry on transient errors (rate limit in body, etc.)

### 4. Cooldown too aggressive (inspired by findfreeai)
- After 3 errors, cooldown grows exponentially (30s → 60s → 120s → 300s)
- findfreeai approach: reduce priority instead of fully disabling

### 5. Key save - Double-save race condition
- `manager.save_api_keys()` then `manager.reload()` could have race
- `save_keys` doesn't handle the case where `cryptography` fails mid-save
