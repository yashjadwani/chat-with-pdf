import json
import logging
import time

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.db.supabase import ApiLogDB

logger = logging.getLogger(__name__)
settings = get_settings()
_query_expansion_failures = 0
_query_expansion_disabled_until = 0.0


class QueryExpansion(BaseModel):
    contextual_query: str = Field(default="")
    bm25_query: str = Field(default="")
    dense_query: str = Field(default="")


SYSTEM_PROMPT = """You are a query expansion assistant for a PDF chat application.

Your job is only to rewrite and expand the user's search query for retrieval.

Rules:
- Do not answer the user's question.
- Do not invent facts, dates, names, clauses, obligations, amounts, page numbers, or conclusions.
- Do not assume anything that is not present in the query or chat history.
- Only use the current query and chat history to clarify references, add synonyms, and create broader search wording.
- Keep the original meaning of the user's query.
- Keep each field under 300 characters.
- Return only valid JSON. No markdown, no preamble.

Return JSON with:
{
  "contextual_query": "The user's query with references resolved from chat history.",
  "bm25_query": "Keyword-rich version with synonyms and exact-match terms.",
  "dense_query": "Broader conceptual version for semantic vector search."
}
"""


def fallback_expansion(query: str) -> QueryExpansion:
    return QueryExpansion(
        contextual_query=query,
        bm25_query=query,
        dense_query=query,
    )


def format_recent_history(
    messages: list[dict],
    max_turns: int = 3,
    max_chars_per_message: int = 320,
) -> str:
    if not messages:
        return ""

    selected = messages[-max_turns * 2 :]
    lines = []
    for message in selected:
        role = "User" if message.get("role") == "user" else "Assistant"
        content = str(message.get("content") or "").strip()
        if content:
            if len(content) > max_chars_per_message:
                content = f"{content[:max_chars_per_message].rstrip()}..."
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _strip_code_fence(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        cleaned = cleaned.removesuffix("```").strip()
    return cleaned


def _normalise_expansion(raw: dict, fallback_query: str) -> QueryExpansion:
    expansion = QueryExpansion.model_validate(raw)
    contextual_query = expansion.contextual_query.strip() or fallback_query
    bm25_query = expansion.bm25_query.strip() or contextual_query
    dense_query = expansion.dense_query.strip() or contextual_query
    return QueryExpansion(
        contextual_query=contextual_query[:300],
        bm25_query=bm25_query[:300],
        dense_query=dense_query[:300],
    )


def _extract_response_debug(data: dict, content: str | None = None) -> dict:
    choices = data.get("choices") if isinstance(data, dict) else None
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    message = first_choice.get("message") if isinstance(first_choice, dict) else {}
    message = message if isinstance(message, dict) else {}
    raw_content = message.get("content") if content is None else content
    reasoning_content = message.get("reasoning_content")

    return {
        "response_keys": list(data.keys()) if isinstance(data, dict) else [],
        "choice_count": len(choices) if isinstance(choices, list) else 0,
        "finish_reason": first_choice.get("finish_reason") if isinstance(first_choice, dict) else None,
        "message_keys": list(message.keys()),
        "content_length": len(raw_content or ""),
        "content_preview": (raw_content or "")[:500],
        "reasoning_content_length": len(reasoning_content or ""),
        "reasoning_content_preview": (reasoning_content or "")[:500],
    }


def _query_expansion_circuit_open() -> bool:
    return time.monotonic() < _query_expansion_disabled_until


def _record_query_expansion_success() -> None:
    global _query_expansion_failures, _query_expansion_disabled_until
    _query_expansion_failures = 0
    _query_expansion_disabled_until = 0.0


def _record_query_expansion_failure(error_message: str) -> None:
    global _query_expansion_failures, _query_expansion_disabled_until
    _query_expansion_failures += 1
    if _query_expansion_failures < settings.query_expansion_failure_threshold:
        return

    _query_expansion_disabled_until = time.monotonic() + settings.query_expansion_cooldown_seconds
    logger.warning(
        "Query expansion circuit opened for %ss after %s failures. Last error: %s",
        settings.query_expansion_cooldown_seconds,
        _query_expansion_failures,
        error_message,
    )


async def expand_query_for_retrieval(
    *,
    original_query: str,
    acronym_expanded_query: str,
    recent_history: str,
    user_id: str | None = None,
    document_id: str | None = None,
    session_id: str | None = None,
) -> QueryExpansion:
    if not settings.query_expansion_enabled:
        return fallback_expansion(acronym_expanded_query)
    if _query_expansion_circuit_open():
        return fallback_expansion(acronym_expanded_query)

    user_prompt = (
        f"Chat history:\n{recent_history or '(none)'}\n\n"
        f"Current query:\n{acronym_expanded_query}\n\n"
        f"Original user wording:\n{original_query}"
    )
    started_at = time.perf_counter()
    request_metadata = {
        "original_query_length": len(original_query),
        "acronym_expanded_query_length": len(acronym_expanded_query),
        "recent_history_length": len(recent_history),
    }

    try:
        async with httpx.AsyncClient(timeout=settings.query_expansion_timeout_seconds) as client:
            response = await client.post(
                f"{settings.opencode_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.opencode_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://chatwithpdf.app",
                    "X-Title": "PDF Chat",
                },
                json={
                    "model": settings.opencode_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": settings.query_expansion_max_tokens,
                    "response_format": {"type": "json_object"},
                    "reasoning": {
                        "effort": "none",
                        "exclude": True,
                    },
                    "temperature": 0.0,
                },
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"].get("content") or ""
        expansion = _normalise_expansion(
            raw=json.loads(_strip_code_fence(content)),
            fallback_query=acronym_expanded_query,
        )
        _record_query_expansion_success()
        usage = data.get("usage") or {}
        ApiLogDB().insert_log(
            purpose="query_expansion",
            model=settings.opencode_model,
            status="success",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=original_query,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            request_metadata=request_metadata,
            response_metadata={
                "contextual_query_length": len(expansion.contextual_query),
                "bm25_query_length": len(expansion.bm25_query),
                "dense_query_length": len(expansion.dense_query),
                "usage_raw": usage,
            },
            response_content=expansion.model_dump_json(),
            raw_response=data,
        )
        return expansion
    except httpx.HTTPStatusError as exc:
        error_message = f"{type(exc).__name__}: {exc.response.status_code} {exc.response.text}"
        logger.warning(f"Query expansion failed, using fallback: {error_message}")
        ApiLogDB().insert_log(
            purpose="query_expansion",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=original_query,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata=request_metadata,
            raw_response={
                "status_code": exc.response.status_code,
                "body": exc.response.text,
            },
            error_message=error_message,
        )
        _record_query_expansion_failure(error_message)
        return fallback_expansion(acronym_expanded_query)
    except httpx.TimeoutException as exc:
        error_message = (
            f"{type(exc).__name__}: query expansion exceeded "
            f"{settings.query_expansion_timeout_seconds}s"
        )
        logger.warning(f"Query expansion failed, using fallback: {error_message}")
        ApiLogDB().insert_log(
            purpose="query_expansion",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=original_query,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata=request_metadata,
            error_message=error_message,
        )
        _record_query_expansion_failure(error_message)
        return fallback_expansion(acronym_expanded_query)
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {str(exc) or repr(exc)}"
        logger.warning(f"Query expansion failed, using fallback: {error_message}")
        response_debug = _extract_response_debug(data, content) if "data" in locals() else None
        ApiLogDB().insert_log(
            purpose="query_expansion",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=original_query,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata=request_metadata,
            response_metadata={"response_debug": response_debug} if response_debug else None,
            raw_response=data if "data" in locals() else None,
            error_message=error_message,
        )
        _record_query_expansion_failure(error_message)
        return fallback_expansion(acronym_expanded_query)
