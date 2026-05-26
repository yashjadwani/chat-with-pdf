import logging
import time

import httpx
from langchain_core.chat_history import InMemoryChatMessageHistory

from app.core.config import get_settings
from app.db.supabase import ApiLogDB, ChatDB

logger = logging.getLogger(__name__)
settings = get_settings()

# Warm in-process cache. Supabase remains the persistent source of truth.
_sessions: dict[str, InMemoryChatMessageHistory] = {}
_summaries: dict[str, str] = {}


def _new_memory() -> InMemoryChatMessageHistory:
    return InMemoryChatMessageHistory()


def get_session_memory(
    session_id: str,
    user_id: str | None = None,
    document_id: str | None = None,
) -> InMemoryChatMessageHistory:
    """
    Get or create a LangChain memory object.
    When user_id/document_id are provided, hydrate it from persistent chat_messages.
    """
    if session_id in _sessions:
        return _sessions[session_id]

    memory = _new_memory()
    if user_id and document_id:
        chat_db = ChatDB()
        message_limit = settings.keep_recent * 2 if _summaries.get(session_id) else settings.summary_threshold
        recent_messages = chat_db.get_recent_messages(
            session_id=session_id,
            limit=message_limit,
        )
        for message in recent_messages:
            if message["role"] == "user":
                memory.add_user_message(message["content"])
            elif message["role"] == "assistant":
                memory.add_ai_message(message["content"])

    _sessions[session_id] = memory
    logger.info(f"Created memory session: {session_id}")
    return memory


def hydrate_summary(session_id: str, summary: str | None) -> None:
    if summary:
        _summaries[session_id] = summary


def save_exchange(
    session_id: str,
    user_id: str,
    document_id: str,
    question: str,
    answer: str,
    citations: list | None = None,
) -> None:
    """Save a question/answer pair to LangChain memory and Supabase."""
    memory = get_session_memory(session_id, user_id, document_id)
    memory.add_user_message(question)
    memory.add_ai_message(answer)

    chat_db = ChatDB()
    chat_db.insert_message(
        session_id=session_id,
        user_id=user_id,
        document_id=document_id,
        role="user",
        content=question,
    )
    chat_db.insert_message(
        session_id=session_id,
        user_id=user_id,
        document_id=document_id,
        role="assistant",
        content=answer,
        citations=citations or [],
    )


async def summarize_if_needed(
    session_id: str,
    user_id: str,
    document_id: str,
) -> None:
    """
    If history grows beyond threshold, summarize older messages and keep
    the last configured number of turns as the live tail.
    """
    memory = get_session_memory(session_id, user_id, document_id)
    messages = memory.messages

    if len(messages) <= settings.summary_threshold:
        return

    tail_count = settings.keep_recent * 2
    older_messages = messages[:-tail_count]
    tail_messages = messages[-tail_count:]

    previous_summary = _summaries.get(session_id, "")
    older_text = "\n".join(
        f"{'User' if message.type == 'human' else 'Assistant'}: {message.content}"
        for message in older_messages
    )

    prompt = (
        "Summarize the older chat history for a document Q&A assistant. "
        "Preserve user intent, important facts, prior answers, and unresolved follow-ups. "
        "Keep it concise and useful for future context.\n\n"
    )
    if previous_summary:
        prompt += f"Existing summary:\n{previous_summary}\n\n"
    prompt += f"Older messages to summarize:\n{older_text}"

    started_at = time.perf_counter()
    usage = {}
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
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
                    "messages": [
                        {
                            "role": "system",
                            "content": "You summarize chat history for a RAG assistant.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 400,
                    "temperature": 0.0,
                },
            )
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage") or {}
    except Exception as exc:
        ApiLogDB().insert_log(
            purpose="memory_summary",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt="memory_summary",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata={
                "older_message_count": len(older_messages),
                "previous_summary_length": len(previous_summary),
            },
            error_message=str(exc),
        )
        logger.warning(f"Failed to summarize memory session {session_id}: {str(exc)}")
        return

    summary = data["choices"][0]["message"]["content"]
    _summaries[session_id] = summary
    memory.messages = tail_messages
    ChatDB().update_summary(session_id=session_id, summary=summary)
    ApiLogDB().insert_log(
        purpose="memory_summary",
        model=settings.opencode_model,
        status="success",
        user_id=user_id,
        document_id=document_id,
        session_id=session_id,
        user_prompt="memory_summary",
        latency_ms=int((time.perf_counter() - started_at) * 1000),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        request_metadata={
            "older_message_count": len(older_messages),
            "tail_message_count": len(tail_messages),
            "previous_summary_length": len(previous_summary),
        },
        response_metadata={
            "summary_length": len(summary),
            "usage_raw": usage,
        },
    )
    logger.info(f"Summarized memory session: {session_id}")


async def get_history_string(
    session_id: str,
    user_id: str,
    document_id: str,
    summary: str | None = None,
) -> str:
    """Return summary plus recent tail as a formatted string for prompts."""
    hydrate_summary(session_id, summary)
    await summarize_if_needed(session_id, user_id, document_id)

    memory = get_session_memory(session_id, user_id, document_id)
    saved_summary = _summaries.get(session_id, "")
    history_messages = memory.messages

    if not saved_summary and not history_messages:
        return ""

    lines = []
    if saved_summary:
        lines.append(f"Summary of earlier conversation: {saved_summary}")

    for message in history_messages:
        role = "User" if message.type == "human" else "Assistant"
        lines.append(f"{role}: {message.content}")

    return "\n".join(lines)


def get_history_messages(session_id: str, user_id: str, document_id: str) -> list[dict]:
    """Return persisted chat history as a list of {role, content} dicts."""
    messages = ChatDB().get_recent_messages(session_id=session_id, limit=200)
    return [
        {
            "role": message["role"],
            "content": message["content"],
            "citations": message.get("citations") or [],
        }
        for message in messages
    ]


def clear_session(session_id: str) -> None:
    """Clear memory, summary, and persisted messages for a session."""
    removed = False
    if session_id in _sessions:
        del _sessions[session_id]
        removed = True
    if session_id in _summaries:
        del _summaries[session_id]
        removed = True
    ChatDB().clear_session_messages(session_id)
    logger.info(f"Cleared memory session: {session_id}")


def active_sessions() -> list[str]:
    """Return list of active in-process session IDs for debugging."""
    return list(_sessions.keys())
