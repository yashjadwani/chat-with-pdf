import app.services.providers as providers_module
from app.services.providers import get_chat_providers


def _set_keys(monkeypatch, custom="", openrouter="", gemini=""):
    settings = providers_module.settings
    monkeypatch.setattr(settings, "custom_api_key", custom)
    monkeypatch.setattr(settings, "openrouter_api_key", openrouter)
    monkeypatch.setattr(settings, "gemini_api_key", gemini)


class TestGetChatProviders:
    def test_all_three_in_fallback_order(self, monkeypatch):
        _set_keys(monkeypatch, custom="a", openrouter="b", gemini="c")
        labels = [p["label"] for p in get_chat_providers()]
        assert labels == ["custom", "gemini", "openrouter"]

    def test_provider_without_key_is_skipped(self, monkeypatch):
        _set_keys(monkeypatch, custom="a", openrouter="b", gemini="")
        labels = [p["label"] for p in get_chat_providers()]
        assert labels == ["custom", "openrouter"]

    def test_openrouter_dormant_until_key_set(self, monkeypatch):
        _set_keys(monkeypatch, custom="a", openrouter="", gemini="c")
        assert "openrouter" not in [p["label"] for p in get_chat_providers()]

    def test_no_keys_means_no_providers(self, monkeypatch):
        _set_keys(monkeypatch)
        assert get_chat_providers() == []

    def test_only_custom_carries_provider_specific_body(self, monkeypatch):
        _set_keys(monkeypatch, custom="a", openrouter="b", gemini="c")
        by_label = {p["label"]: p for p in get_chat_providers()}
        assert "reasoning" in by_label["custom"]["body_extra"]
        assert by_label["openrouter"]["body_extra"] == {}
        assert by_label["gemini"]["body_extra"] == {}
