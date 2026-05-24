import logging
import json
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from app.api.deps import get_current_user_id
from app.db.supabase import DocumentDB
from app.db.chroma import ChromaStore
from app.models.chat import ChatQueryRequest, ChatQueryResponse, ChatHistoryResponse
from app.services.retrieval import retrieve_chunks, filter_by_query_terms
from app.services.llm import generate_answer, generate_answer_stream
from app.services.memory import get_history_string, save_exchange, get_history_messages, clear_session
from langsmith import traceable

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@traceable(name="chat_query")
async def _run_rag_pipeline(
    question: str,
    document_id: str,
    session_id: str,
) -> tuple:
    """
    Core RAG pipeline — wrapped in LangSmith trace.
    Returns (answer, citations, model_used).
    """
    # Step 1 — Retrieve relevant chunks
    citations = retrieve_chunks(question=question, document_id=document_id, top_k=5)
    citations = filter_by_query_terms(question=question, citations=citations)

    # Step 2 — Get conversation history
    conversation_history = await get_history_string(session_id)

    # Step 3 — Generate answer with LLM
    answer, model_used = await generate_answer(
        question=question,
        citations=citations,
        conversation_history=conversation_history,
    )

    # Step 4 — Save exchange to memory
    save_exchange(
        session_id=session_id,
        question=question,
        answer=answer,
    )

    return answer, citations, model_used


@router.post("/query", response_model=ChatQueryResponse)
async def query_document(
    request: ChatQueryRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Query a document with a natural language question.

    - Verifies document exists and belongs to the user
    - Retrieves top-k relevant chunks from ChromaDB (filtered by document_id)
    - Passes chunks + conversation history to LLM
    - Returns answer with page number citations
    - Saves exchange to in-session memory
    """
    doc_db = DocumentDB()
    chroma_store = ChromaStore()

    # Verify document ownership
    document = doc_db.get_document(
        document_id=request.document_id,
        user_id=user_id,
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    # Verify document is ready
    if document["status"] != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is not ready for querying. Current status: {document['status']}",
        )

    # Verify document has embeddings
    if not chroma_store.document_exists(request.document_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document embeddings not found. Please re-upload the document.",
        )

    # Validate question
    question = request.question.strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty.",
        )
    if len(question) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question too long. Maximum 2000 characters.",
        )

    # Session ID — user + document scoped memory
    session_id = request.session_id or f"{user_id}_{request.document_id}"

    try:
        answer, citations, model_used = await _run_rag_pipeline(
            question=question,
            document_id=request.document_id,
            session_id=session_id,
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
    doc_db = DocumentDB()
    chroma_store = ChromaStore()

    document = doc_db.get_document(
        document_id=request.document_id,
        user_id=user_id,
    )
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
    if not chroma_store.document_exists(request.document_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document embeddings not found. Please re-upload the document.",
        )

    question = request.question.strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty.",
        )
    if len(question) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question too long. Maximum 2000 characters.",
        )

    session_id = request.session_id or f"{user_id}_{request.document_id}"
    citations = retrieve_chunks(question=question, document_id=request.document_id, top_k=5)
    citations = filter_by_query_terms(question=question, citations=citations)
    conversation_history = await get_history_string(session_id)

    async def events():
        answer_parts = []
        yield _sse(
            "citations",
            [citation.model_dump() for citation in citations],
        )
        try:
            async for token in generate_answer_stream(
                question=question,
                citations=citations,
                conversation_history=conversation_history,
            ):
                answer_parts.append(token)
                yield _sse("token", token)

            answer = "".join(answer_parts)
            save_exchange(session_id=session_id, question=question, answer=answer)
            yield _sse(
                "done",
                {
                    "model_used": "opencode",
                    "document_id": request.document_id,
                    "question": question,
                },
            )
        except RuntimeError as exc:
            yield _sse("error", str(exc))

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/history/{document_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    document_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get the conversation history for a document session."""
    session_id = f"{user_id}_{document_id}"
    messages = get_history_messages(session_id)

    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages,
    )


@router.delete("/history/{document_id}")
async def clear_chat_history(
    document_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Clear the conversation memory for a document session."""
    session_id = f"{user_id}_{document_id}"
    clear_session(session_id)
    return {"message": "Conversation history cleared.", "session_id": session_id}
