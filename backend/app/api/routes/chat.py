import json
import logging
import time
import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langsmith import traceable

from app.api.deps import get_current_user_id
from app.core.config import get_settings
from app.db.chroma import ChromaStore, reload_modal_volume_if_needed
from app.db.supabase import ApiLogDB, ChatDB, DocumentDB
from app.models.chat import ChatHistoryResponse, ChatQueryRequest, ChatQueryResponse
from app.services.analysis import (
    extract_comparison_facts,
    generate_comparison_answer,
    is_comparison_question,
    rank_comparison_facts,
)
from app.services.llm import generate_answer, generate_answer_stream
from app.services.memory import (
    clear_session,
    get_history_messages,
    get_history_string,
    save_exchange,
)
from app.services.query_expansion import expand_query_for_retrieval, format_recent_history
from app.services.retrieval import build_acronym_expanded_query, filter_by_query_terms, retrieve_chunks
from app.services.summary import generate_summary_answer, get_summary_citations, is_summary_question

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/chat", tags=["chat"])


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _get_ready_document(document_id: str, user_id: str) -> dict:
    doc_db = DocumentDB()
    await reload_modal_volume_if_needed()
    chroma_store = ChromaStore()

    document = doc_db.get_document(document_id=document_id, user_id=user_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    if document["status"] != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is not ready for querying. Current status: {document['status']}",
        )
    if not chroma_store.document_exists(document_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document embeddings not found. Please re-upload the document.",
        )

    return document


def _get_user_document(document_id: str, user_id: str) -> dict:
    document = DocumentDB().get_document(document_id=document_id, user_id=user_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return document


def _validate_question(question: str) -> str:
    cleaned = question.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty.",
        )
    if len(cleaned) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question too long. Maximum 2000 characters.",
        )
    return cleaned


async def _expand_query_for_session(
    question: str,
    document_id: str,
    user_id: str,
    session_id: str,
):
    acronym_expanded_query = build_acronym_expanded_query(question=question, document_id=document_id)
    recent_messages = ChatDB().get_recent_messages(
        session_id=session_id,
        limit=6,
        user_id=user_id,
        document_id=document_id,
    )
    return await expand_query_for_retrieval(
        original_query=question,
        acronym_expanded_query=acronym_expanded_query,
        recent_history=format_recent_history(recent_messages, max_turns=3),
        user_id=user_id,
        document_id=document_id,
        session_id=session_id,
    )


@traceable(name="chat_query")
async def _run_rag_pipeline(
    question: str,
    document_id: str,
    user_id: str,
    session: dict,
) -> tuple:
    """
    Core RAG pipeline wrapped in LangSmith trace.
    Returns (answer, citations, model_used).
    """
    session_id = session["session_id"]
    summary_mode = is_summary_question(question)
    analytical_mode = is_comparison_question(question)

    if summary_mode:
        citations = get_summary_citations(document_id=document_id, max_chunks=14)
    else:
        expansion = await _expand_query_for_session(
            question=question,
            document_id=document_id,
            user_id=user_id,
            session_id=session_id,
        )
        citations = retrieve_chunks(
            question=question,
            document_id=document_id,
            top_k=12 if analytical_mode else 5,
            bm25_query=expansion.bm25_query,
            dense_query=expansion.dense_query,
            rerank_query=expansion.contextual_query,
        )

    if not analytical_mode and not summary_mode:
        filter_query = expansion.contextual_query if not summary_mode else question
        citations = filter_by_query_terms(question=filter_query, citations=citations)

    conversation_history = await get_history_string(
        session_id=session_id,
        user_id=user_id,
        document_id=document_id,
        summary=session.get("summary"),
    )

    if summary_mode:
        answer, model_used = await generate_summary_answer(
            question=question,
            citations=citations,
            conversation_history=conversation_history,
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
        )
    elif analytical_mode:
        facts = await extract_comparison_facts(
            question=question,
            citations=citations,
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
        )
        ranked_facts = rank_comparison_facts(question, facts)
        answer, model_used = await generate_comparison_answer(
            question=question,
            citations=citations,
            ranked_facts=ranked_facts,
            conversation_history=conversation_history,
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
        )
    else:
        answer, model_used = await generate_answer(
            question=question,
            citations=citations,
            conversation_history=conversation_history,
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
        )

    save_exchange(
        session_id=session_id,
        user_id=user_id,
        document_id=document_id,
        question=question,
        answer=answer,
        citations=[citation.model_dump() for citation in citations],
    )

    return answer, citations, model_used


@router.post("/query", response_model=ChatQueryResponse)
async def query_document(
    request: ChatQueryRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Query a document with a natural language question."""
    await _get_ready_document(document_id=request.document_id, user_id=user_id)
    question = _validate_question(request.question)
    session = ChatDB().get_or_create_default_session(
        user_id=user_id,
        document_id=request.document_id,
    )

    try:
        answer, citations, model_used = await _run_rag_pipeline(
            question=question,
            document_id=request.document_id,
            user_id=user_id,
            session=session,
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"RAG pipeline error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your question. Please try again.",
        )

    return ChatQueryResponse(
        answer=answer,
        citations=citations,
        model_used=model_used,
        document_id=request.document_id,
        question=question,
    )


@router.post("/stream")
async def stream_document_query(
    request: ChatQueryRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Stream an answer for a document query as server-sent events."""
    await _get_ready_document(document_id=request.document_id, user_id=user_id)
    question = _validate_question(request.question)
    session = ChatDB().get_or_create_default_session(
        user_id=user_id,
        document_id=request.document_id,
    )
    session_id = session["session_id"]

    expansion = await _expand_query_for_session(
        question=question,
        document_id=request.document_id,
        user_id=user_id,
        session_id=session_id,
    )
    citations = retrieve_chunks(
        question=question,
        document_id=request.document_id,
        top_k=5,
        bm25_query=expansion.bm25_query,
        dense_query=expansion.dense_query,
        rerank_query=expansion.contextual_query,
    )
    citations = filter_by_query_terms(question=expansion.contextual_query, citations=citations)
    conversation_history = await get_history_string(
        session_id=session_id,
        user_id=user_id,
        document_id=request.document_id,
        summary=session.get("summary"),
    )

    async def events():
        answer_parts = []
        raw_events = []
        started_at = time.perf_counter()
        request_metadata = {
            "question_length": len(question),
            "retrieved_chunks": len(citations),
            "chunk_refs": [
                {"page": citation.page_number, "chunk_index": citation.chunk_index}
                for citation in citations
            ],
            "conversation_history_length": len(conversation_history),
            "stream": True,
        }

        citation_payload = [citation.model_dump() for citation in citations]
        raw_events.append({"event": "citations", "data": citation_payload})
        yield _sse("citations", citation_payload)
        try:
            async for token in generate_answer_stream(
                question=question,
                citations=citations,
                conversation_history=conversation_history,
            ):
                answer_parts.append(token)
                raw_events.append({"event": "token", "content": token})
                yield _sse("token", token)

            answer = "".join(answer_parts)
            done_payload = {
                "model_used": settings.opencode_model,
                "document_id": request.document_id,
                "question": question,
            }
            raw_events.append({"event": "done", "data": done_payload})
            save_exchange(
                session_id=session_id,
                user_id=user_id,
                document_id=request.document_id,
                question=question,
                answer=answer,
                citations=[citation.model_dump() for citation in citations],
            )
            ApiLogDB().insert_log(
                purpose="chat_answer",
                model=settings.opencode_model,
                status="success",
                user_id=user_id,
                document_id=request.document_id,
                session_id=session_id,
                user_prompt=question,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                request_metadata=request_metadata,
                response_metadata={
                    "answer_length": len(answer),
                    "stream_events": len(raw_events),
                    "token_events": max(len(raw_events) - 1, 0),
                },
                response_content=answer,
                raw_response=raw_events,
            )
            yield _sse("done", done_payload)
        except RuntimeError as exc:
            raw_events.append({"event": "error", "data": str(exc)})
            ApiLogDB().insert_log(
                purpose="chat_answer",
                model=settings.opencode_model,
                status="error",
                user_id=user_id,
                document_id=request.document_id,
                session_id=session_id,
                user_prompt=question,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                request_metadata=request_metadata,
                response_content="".join(answer_parts) or None,
                raw_response=raw_events,
                error_message=str(exc),
            )
            yield _sse("error", str(exc))
        except asyncio.CancelledError:
            answer = "".join(answer_parts)
            ApiLogDB().insert_log(
                purpose="chat_answer",
                model=settings.opencode_model,
                status="error",
                user_id=user_id,
                document_id=request.document_id,
                session_id=session_id,
                user_prompt=question,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                request_metadata=request_metadata,
                response_metadata={
                    "answer_length": len(answer),
                    "stream_events": len(raw_events),
                    "cancelled": True,
                },
                response_content=answer or None,
                raw_response=raw_events,
                error_message="Stream cancelled before completion.",
            )
            raise

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/history/{document_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    document_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get the persisted conversation history for a document session."""
    _get_user_document(document_id=document_id, user_id=user_id)
    session = ChatDB().get_or_create_default_session(
        user_id=user_id,
        document_id=document_id,
    )
    messages = get_history_messages(
        session_id=session["session_id"],
        user_id=user_id,
        document_id=document_id,
    )

    return ChatHistoryResponse(
        session_id=session["session_id"],
        messages=messages,
    )


@router.delete("/history/{document_id}")
async def clear_chat_history(
    document_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Clear the persisted conversation memory for a document session."""
    await _get_ready_document(document_id=document_id, user_id=user_id)
    session = ChatDB().get_or_create_default_session(
        user_id=user_id,
        document_id=document_id,
    )
    clear_session(
        session_id=session["session_id"],
        user_id=user_id,
        document_id=document_id,
    )
    return {"message": "Conversation history cleared.", "session_id": session["session_id"]}
