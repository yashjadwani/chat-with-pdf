import app.services.providers as providers_module
from app.services.providers import get_chat_providers


def _set_keys(monkeypatch, custom="", openrouter="", gemini=""):
    s = providers_module.settings
    monkeypatch.setattr(s, "custom_api_key", custom)
    monkeypatch.setattr(s, "openrouter_api_key", openrouter)
    monkeypatch.setattr(s, "gemini_api_key", gemini)
    # distinct models so the tests can tell the entries apart
    monkeypatch.setattr(s, "openrouter_llm_primary", "or-primary")
    monkeypatch.setattr(s, "openrouter_llm_fallback", "or-fallback")
    monkeypatch.setattr(s, "custom_model", "qwen-test")


def _labels(): return [p["label"] for p in get_chat_providers()]


class TestGetChatProviders:
    def test_all_in_fallback_order(self, monkeypatch):
        _set_keys(monkeypatch, custom="a", openrouter="b", gemini="c")
        assert _labels() == ["openrouter", "openrouter", "custom", "gemini"]

    def test_openrouter_primary_then_fallback_model(self, monkeypatch):
        _set_keys(monkeypatch, custom="a", openrouter="b", gemini="c")
        models = [p["model"] for p in get_chat_providers() if p["label"] == "openrouter"]
        assert models == ["or-primary", "or-fallback"]

    def test_custom_uses_custom_model_not_base_url(self, monkeypatch):
        _set_keys(monkeypatch, custom="a", openrouter="b", gemini="c")
        custom = next(p for p in get_chat_providers() if p["label"] == "custom")
        assert custom["model"] == "qwen-test"

    def test_provider_without_key_is_skipped(self, monkeypatch):
        _set_keys(monkeypatch, custom="a", openrouter="b", gemini="")
        assert _labels() == ["openrouter", "openrouter", "custom"]

    def test_openrouter_dormant_until_key_set(self, monkeypatch):
        _set_keys(monkeypatch, custom="a", openrouter="", gemini="c")
        assert _labels() == ["custom", "gemini"]

    def test_no_keys_means_no_providers(self, monkeypatch):
        _set_keys(monkeypatch)
        assert get_chat_providers() == []

    def test_only_custom_carries_retry_settings(self, monkeypatch):
        _set_keys(monkeypatch, custom="a", openrouter="b", gemini="c")
        for p in get_chat_providers():
            if p["label"] == "custom":
                assert {"timeout", "max_retries"} <= set(p["body_extra"])
            else:
                assert p["body_extra"] == {}