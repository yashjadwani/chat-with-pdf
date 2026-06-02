import json
import logging
import time

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.db.supabase import ApiLogDB

logger = logging.getLogger(__name__)
settings = get_settings()


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


def format_recent_history(messages: list[dict], max_turns: int = 3) -> str:
    if not messages:
        return ""

    selected = messages[-max_turns * 2 :]
    lines = []
    for message in selected:
        role = "User" if message.get("role") == "user" else "Assistant"
        content = str(message.get("content") or "").strip()
        if content:
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
                    "temperature": 0.0,
                },
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        expansion = _normalise_expansion(
            raw=json.loads(_strip_code_fence(content)),
            fallback_query=acronym_expanded_query,
        )
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
    except Exception as exc:
        logger.warning(f"Query expansion failed, using fallback: {str(exc)}")
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
            error_message=str(exc),
        )
        return fallback_expansion(acronym_expanded_query)
