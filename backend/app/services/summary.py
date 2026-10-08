import logging
import time

import httpx

from app.core.config import get_settings
from app.db.chroma import ChromaStore
from app.db.supabase import ApiLogDB
from app.models.chat import Citation
from app.services.retrieval import format_context

logger = logging.getLogger(__name__)
settings = get_settings()

SUMMARY_TERMS = {
    "summarize",
    "summarise",
    "summary",
    "overview",
    "main points",
    "key points",
    "key takeaways",
    "takeaways",
    "brief",
}


def is_summary_question(question: str) -> bool:
    question_lower = question.lower()
    return any(term in question_lower for term in SUMMARY_TERMS)


def get_summary_citations(document_id: str, max_chunks: int = 14) -> list[Citation]:
    chunks = ChromaStore().get_document_chunks(document_id=document_id, active_only=True)
    if not chunks:
        return []

    chunks = sorted(
        chunks,
        key=lambda chunk: (
            int(chunk["meta"].get("page_number") or chunk["meta"].get("page") or 0),
            int(chunk["meta"].get("chunk_index") or chunk["meta"].get("chunk") or 0),
        ),
    )

    if len(chunks) <= max_chunks:
        sampled = chunks
    else:
        step = (len(chunks) - 1) / (max_chunks - 1)
        indexes = sorted({round(index * step) for index in range(max_chunks)})
        sampled = [chunks[index] for index in indexes]

    return [
        Citation(
            page_number=int(chunk["meta"].get("page_number") or chunk["meta"].get("page") or 0),
            chunk_text=chunk["text"],
            chunk_index=int(chunk["meta"].get("chunk_index") or chunk["meta"].get("chunk") or 0),
        )
        for chunk in sampled
    ]


async def generate_summary_answer(
    question: str,
    citations: list[Citation],
    conversation_history: str,
    user_id: str,
    document_id: str,
    session_id: str,
) -> tuple[str, str]:
    context = format_context(citations)
    prompt = (
        "Summarize the document using only the representative document context below. "
        "Give a clear, useful summary for a non-technical reader unless the document "
        "itself requires technical detail. Include important themes, decisions, methods, "
        "results, or conclusions when present. Cite page numbers for major points. "
        "If the context is only a sample, say that the summary is based on representative pages.\n\n"
        f"Previous conversation:\n{conversation_history or 'None'}\n\n"
        f"User request:\n{question}\n\n"
        f"Representative document context:\n{context}"
    )
    started_at = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.openrouter_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://chatwithpdf.app",
                    "X-Title": "Chat with PDF",
                },
                json={
                    "model": settings.openrouter_llm_primary,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": settings.document_summary_max_tokens,
                    "reasoning": {"effort": "none","exclude": True,},
                    "thinking": {"type": "disabled"}, 
                    "temperature": 0.1,
                },
            )
            response.raise_for_status()
            data = response.json()

        answer = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        ApiLogDB().insert_log(
            purpose="document_summary",
            model=settings.openrouter_llm_primary,
            status="success",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            request_metadata={
                "summary_chunks": len(citations),
                "context_char_count": len(context),
            },
            response_metadata={"answer_length": len(answer), "usage_raw": usage},
            response_content=answer,
            raw_response=data,
        )
        return answer, settings.openrouter_llm_primary
    except Exception as exc:
        logger.error(f"Document summary generation failed: {str(exc)}")
        ApiLogDB().insert_log(
            purpose="document_summary",
            model=settings.openrouter_llm_primary,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata={"summary_chunks": len(citations)},
            error_message=str(exc),
        )
        raise RuntimeError("LLM call failed. Please try again later.") from exc
