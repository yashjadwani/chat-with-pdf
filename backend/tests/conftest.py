"""
Pytest configuration.

app.core.config.Settings validates required env vars at import time, and most
app modules call get_settings() at module level. Provide harmless dummies so
pure-logic modules can be imported in environments without a real .env (CI).
setdefault keeps a developer's real .env values when present.
"""

import os

_DUMMY_ENV = {
    "SUPABASE_URL": "http://localhost:54321",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "OPENROUTER_API_KEY": "test-openrouter-key",
    "OPENCODE_API_KEY": "test-opencode-key",
}

for key, value in _DUMMY_ENV.items():
    os.environ.setdefault(key, value)
