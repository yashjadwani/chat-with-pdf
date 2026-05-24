import logging

import httpx
from langchain.memory import ConversationBufferWindowMemory

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# In-process session store, keyed by session_id.
# Lives in Modal container memory and is not persisted across restarts.
_sessions: dict[str, ConversationBufferWindowMemory] = {}
_summaries: dict[str, str] = {}

def get_session_memory(session_id: str) -> ConversationBufferWindowMemory:
    """
    Get or create a ConversationBufferWindowMemory for a session.
    Session ID is typically f"{user_id}_{document_id}".
    """
    if session_id not in _sessions:
        _sessions[session_id] = ConversationBufferWindowMemory(
            k=settings.memory_window_size,
            return_messages=True,
            human_prefix="User",
            ai_prefix="Assistant",
        )
        logger.info(f"Created new memory session: {session_id}")

    return _sessions[session_id]


def save_exchange(session_id: str, question: str, answer: str) -> None:
    """Save a question/answer pair to the session memory."""
    memory = get_session_memory(session_id)
    memory.save_context(
        inputs={"input": question},
        outputs={"output": answer},
    )


async def summarize_if_needed(session_id: str) -> None:
    """
    If history grows beyond 20 messages, summarize older messages and keep
    the last two turns as the live tail for follow-up questions.
    """
    memory = get_session_memory(session_id)
    messages = memory.chat_memory.messages

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
    except Exception as exc:
        logger.warning(f"Failed to summarize memory session {session_id}: {str(exc)}")
        return

    _summaries[session_id] = data["choices"][0]["message"]["content"]
    memory.chat_memory.messages = tail_messages
    logger.info(f"Summarized memory session: {session_id}")


async def get_history_string(session_id: str) -> str:
    """
    Return summary plus the recent tail as a formatted string for prompts.
    Summarizes before building context when the session exceeds 20 messages.
    """
    await summarize_if_needed(session_id)

    memory = get_session_memory(session_id)
    summary = _summaries.get(session_id, "")
    history_messages = memory.chat_memory.messages

    if not summary and not history_messages:
        return ""

    lines = []
    if summary:
        lines.append(f"Summary of earlier conversation: {summary}")

    for message in history_messages:
        role = "User" if message.type == "human" else "Assistant"
        lines.append(f"{role}: {message.content}")

    return "\n".join(lines)


def get_history_messages(session_id: str) -> list[dict]:
    """Return summary and recent history as a list of {role, content} dicts."""
    memory = get_session_memory(session_id)
    result = []

    summary = _summaries.get(session_id)
    if summary:
        result.append(
            {
                "role": "system",
                "content": f"Summary of earlier conversation: {summary}",
            }
        )

    for message in memory.chat_memory.messages:
        role = "user" if message.type == "human" else "assistant"
        result.append({"role": role, "content": message.content})

    return result


def clear_session(session_id: str) -> None:
    """Clear memory and summary for a session."""
    removed = False
    if session_id in _sessions:
        del _sessions[session_id]
        removed = True
    if session_id in _summaries:
        del _summaries[session_id]
        removed = True
    if removed:
        logger.info(f"Cleared memory session: {session_id}")


def active_sessions() -> list[str]:
    """Return list of active session IDs for debugging."""
    return list(_sessions.keys())
