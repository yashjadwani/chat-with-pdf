import logging
import json
import time

import httpx

from app.core.config import get_settings
from app.db.supabase import ApiLogDB
from app.models.chat import Citation
from app.services.retrieval import format_context

logger = logging.getLogger(__name__)
settings = get_settings()

SYSTEM_PROMPT = """You are a helpful document assistant for "Chat with PDF".

Your job is to answer questions based ONLY on the document content provided below.

Rules:
- Answer only from the provided document context. Do not use outside knowledge.
- Always cite the page number(s) where you found the information, like: (Page 3) or (Pages 3, 7).
- If the answer is not found in the document, say clearly: "I couldn't find this information in the document."
- Be concise and accurate.
- If the question is a follow-up referring to previous conversation, use the conversation history to understand context.

Document context will be provided in the user message."""


def build_prompt(
    question: str,
    context: str,
    conversation_history: str,
) -> list[dict]:
    """
    Build the messages array for the Opencode API call.
    Includes system prompt, optional conversation history, and the current question with context.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if conversation_history:
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Previous conversation:\n{conversation_history}\n\n"
                    "(Continue the conversation below)"
                ),
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": "Understood. I'll continue based on our conversation and the document.",
            }
        )

    user_message = f"""Document excerpts:
{context}

---

Question: {question}"""

    messages.append({"role": "user", "content": user_message})
    return messages


async def stream_opencode(
    messages: list[dict],
    model: str,
):
    """Yield assistant tokens from the Opencode streaming chat endpoint."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"{settings.opencode_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.opencode_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://chatwithpdf.app",
                "X-Title": "Chat with PDF",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.1,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue

                payload = line.removeprefix("data: ").strip()
                if payload == "[DONE]":
                    break

                data = json.loads(payload)
                token = data["choices"][0].get("delta", {}).get("content")
                if token:
                    yield token


async def generate_answer(
    question: str,
    citations: list[Citation],
    conversation_history: str,
    user_id: str | None = None,
    document_id: str | None = None,
    session_id: str | None = None,
) -> tuple[str, str]:
    """
    Generate an answer using retrieved chunks.
    Returns (answer_text, model_used).
    """
    context = format_context(citations)
    messages = build_prompt(
        question=question,
        context=context,
        conversation_history=conversation_history,
    )

    started_at = time.perf_counter()
    request_metadata = {
        "question_length": len(question),
        "retrieved_chunks": len(citations),
        "chunk_refs": [
            {"page": citation.page_number, "chunk_index": citation.chunk_index}
            for citation in citations
        ],
        "context_char_count": len(context),
        "conversation_history_length": len(conversation_history),
        "stream": False,
    }
    try:
        logger.info(f"Calling Opencode model: {settings.opencode_model}")
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.opencode_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.opencode_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://chatwithpdf.app",
                    "X-Title": "Chat with PDF",
                },
                json={
                    "model": settings.opencode_model,
                    "messages": messages,
                    "temperature": 0.1,
                },
            )
            response.raise_for_status()
            data = response.json()
        answer = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        ApiLogDB().insert_log(
            purpose="chat_answer",
            model=settings.opencode_model,
            status="success",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            request_metadata=request_metadata,
            response_metadata={
                "answer_length": len(answer),
                "usage_raw": usage,
                "provider_id": data.get("id"),
                "provider_created": data.get("created"),
                "provider_object": data.get("object"),
            },
            response_content=answer,
            raw_response=data,
        )
        return answer, settings.opencode_model
    except httpx.HTTPStatusError as exc:
        logger.error(f"Opencode model error: {exc.response.status_code} {exc.response.text}")
        ApiLogDB().insert_log(
            purpose="chat_answer",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata=request_metadata,
            raw_response={
                "status_code": exc.response.status_code,
                "body": exc.response.text,
            },
            error_message=f"{exc.response.status_code} {exc.response.text}",
        )
        raise RuntimeError("LLM call failed. Please try again later.") from exc
    except Exception as exc:
        logger.error(f"Opencode model exception: {str(exc)}")
        ApiLogDB().insert_log(
            purpose="chat_answer",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata=request_metadata,
            error_message=str(exc),
        )
        raise RuntimeError("LLM call failed. Please try again later.") from exc


async def generate_answer_stream(
    question: str,
    citations: list[Citation],
    conversation_history: str,
):
    """Yield answer tokens using retrieved chunks."""
    context = format_context(citations)
    messages = build_prompt(
        question=question,
        context=context,
        conversation_history=conversation_history,
    )

    try:
        logger.info(f"Streaming Opencode model: {settings.opencode_model}")
        async for token in stream_opencode(messages=messages, model=settings.opencode_model):
            yield token
    except httpx.HTTPStatusError as exc:
        logger.error(f"Opencode stream error: {exc.response.status_code} {exc.response.text}")
        raise RuntimeError("LLM stream failed. Please try again later.") from exc
    except Exception as exc:
        logger.error(f"Opencode stream exception: {str(exc)}")
        raise RuntimeError("LLM stream failed. Please try again later.") from exc
