"""
Multi-provider chat completion with ordered fallback.

Every provider here speaks the OpenAI /chat/completions shape, so one code path
covers all three. They are tried in order and the first success wins:

  1. Opencode   (primary)
  2. Gemini     (fallback, via Google's OpenAI-compatible endpoint)
  3. OpenRouter (last resort)

A provider with no API key is skipped. If every configured provider fails, the
caller gets a RuntimeError and can log/surface a single failure.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_chat_providers() -> list[dict]:
    """Ordered chat providers that have an API key configured."""
    providers = [
        {
            "label": "openrouter",
            "base_url": settings.openrouter_base_url,
            "api_key": settings.openrouter_api_key,
            "model": settings.openrouter_llm_primary,
            "body_extra": {},
        },
        {
            "label": "openrouter",
            "base_url": settings.openrouter_base_url,
            "api_key": settings.openrouter_api_key,
            "model": settings.openrouter_llm_fallback,
            "body_extra": {"timeout":180.0, "max_retries":10},
        },
        {
            "label": "custom",
            "base_url": settings.custom_base_url,
            "api_key": settings.custom_api_key,
            "model": settings.custom_model,
            "body_extra": {},
        },
        {
            "label": "gemini",
            "base_url": settings.gemini_base_url,
            "api_key": settings.gemini_api_key,
            "model": settings.gemini_model,
            "body_extra": {},
        }
    ]
    return [provider for provider in providers if provider["api_key"]]


async def chat_completion(
    messages: list[dict],
    max_tokens: int,
    temperature: float = 0.1,
    timeout: float = 60.0,
) -> tuple[dict, str, str]:
    """
    Call each provider in order until one succeeds.

    Returns (response_json, provider_label, model). Raises RuntimeError if no
    provider is configured or all of them fail.
    """
    providers = get_chat_providers()
    if not providers:
        raise RuntimeError("No LLM provider API keys are configured.")

    last_error: Exception | None = None
    for provider in providers:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{provider['base_url']}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {provider['api_key']}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://chatwithpdf.app",
                        "X-Title": "Chat with PDF",
                    },
                    json={
                        "model": provider["model"],
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        **provider["body_extra"],
                    },
                )
                response.raise_for_status()
                return response.json(), provider["label"], provider["model"]
        except Exception as exc:  # noqa: BLE001 - fall through to the next provider
            last_error = exc
            detail = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else str(exc)
            logger.warning(
                "LLM provider '%s' (%s) failed, trying next: %s",
                provider["label"],
                provider["model"],
                detail,
            )

    raise RuntimeError("All LLM providers failed.") from last_error


async def stream_chat_completion(
    messages: list[dict],
    max_tokens: int,
    temperature: float = 0.1,
    timeout: float = 60.0,
):
    """
    Stream tokens with the same ordered fallback as chat_completion.

    Yields tuples: ("model", "<label>/<model>") once, before the first token,
    then ("token", <text>) for each token. Fallback only happens before the
    first token is emitted — once a provider starts streaming we are committed
    to it (we can't un-send tokens already delivered to the client).
    """
    providers = get_chat_providers()
    if not providers:
        raise RuntimeError("No LLM provider API keys are configured.")

    last_error: Exception | None = None
    for provider in providers:
        started = False
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{provider['base_url']}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {provider['api_key']}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://chatwithpdf.app",
                        "X-Title": "Chat with PDF",
                    },
                    json={
                        "model": provider["model"],
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "stream": True,
                        **provider["body_extra"],
                    },
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line.removeprefix("data: ").strip()
                        if payload == "[DONE]":
                            break
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        token = data["choices"][0].get("delta", {}).get("content")
                        if token:
                            if not started:
                                started = True
                                yield ("model", f"{provider['label']}/{provider['model']}")
                            yield ("token", token)
            if started:
                return
        except Exception as exc:  # noqa: BLE001
            if started:
                raise  # already streaming this provider; cannot fall back mid-stream
            last_error = exc
            detail = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else str(exc)
            logger.warning(
                "LLM streaming provider '%s' (%s) failed, trying next: %s",
                provider["label"],
                provider["model"],
                detail,
            )

    raise RuntimeError("All LLM providers failed for streaming.") from last_error
