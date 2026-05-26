from pydantic import BaseModel, Field
from typing import Optional


class ChatQueryRequest(BaseModel):
    document_id: str
    question: str
    session_id: Optional[str] = None  # for memory keying; defaults to document_id


class Citation(BaseModel):
    page_number: int
    chunk_text: str
    chunk_index: int


class ChatQueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    model_used: str
    document_id: str
    question: str


class ChatMessage(BaseModel):
    role: str  # "human" or "assistant"
    content: str
    citations: list[Citation] = Field(default_factory=list)


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessage]
