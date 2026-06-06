import json
import logging
import re
import time

import httpx

from app.core.config import get_settings
from app.db.supabase import ApiLogDB
from app.models.chat import Citation
from app.services.retrieval import format_context

logger = logging.getLogger(__name__)
settings = get_settings()

COMPARISON_TERMS = {
    "best",
    "highest",
    "lowest",
    "most",
    "least",
    "compare",
    "rank",
    "benefited",
    "improved",
    "better",
    "worse",
    "performance",
    "score",
    "value",
    "rate",
    "percentage",
    "cost",
    "time",
    "metric",
    "benefit",
    "benefits",
}

LOWER_IS_BETTER_TERMS = {
    "lowest",
    "least",
    "smallest",
    "minimum",
    "cheapest",
    "shortest",
    "fastest",
    "worse",
}


def is_comparison_question(question: str) -> bool:
    question_lower = question.lower()
    return any(term in question_lower for term in COMPARISON_TERMS)


def _parse_json_array(raw: str) -> list[dict]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        parsed = json.loads(match.group(0))

    return parsed if isinstance(parsed, list) else []


async def extract_comparison_facts(
    question: str,
    citations: list[Citation],
    user_id: str,
    document_id: str,
    session_id: str,
) -> list[dict]:
    context = format_context(citations)
    prompt = (
        "Extract structured comparison facts from the document evidence.\n\n"
        f"Question:\n{question}\n\n"
        f"Evidence:\n{context}\n\n"
        "Return only valid JSON. Return an array of objects with this schema:\n"
        '[{"item":"thing being compared","attribute":"property, measure, or outcome",'
        '"value":number_or_null,"unit":"%, decimal, count, score, currency, time, or null",'
        '"page":page_number_or_null,"evidence":"short evidence text"}]\n\n'
        "Rules:\n"
        "- Only extract facts explicitly supported by the evidence.\n"
        "- Do not invent missing values.\n"
        "- If a comparison fact has no numeric value, use null for value.\n"
        "- Return each supported item/attribute separately.\n"
        "- This must work for any document domain, not only machine learning.\n"
    )
    started_at = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=settings.comparison_extraction_timeout_seconds) as client:
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
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                },
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        facts = _parse_json_array(content)
        usage = data.get("usage") or {}
        ApiLogDB().insert_log(
            purpose="comparison_extraction",
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
            request_metadata={
                "retrieved_chunks": len(citations),
                "context_char_count": len(context),
            },
            response_metadata={"facts_extracted": len(facts), "usage_raw": usage},
            response_content=content,
            raw_response=data,
        )
        return facts
    except httpx.HTTPStatusError as exc:
        error_message = f"{exc.response.status_code} {exc.response.text}"
        logger.error(f"Comparison fact extraction failed: {error_message}")
        ApiLogDB().insert_log(
            purpose="comparison_extraction",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata={"retrieved_chunks": len(citations)},
            raw_response={
                "status_code": exc.response.status_code,
                "body": exc.response.text,
            },
            error_message=error_message,
        )
        return []
    except httpx.TimeoutException as exc:
        error_message = (
            f"{type(exc).__name__}: comparison extraction exceeded "
            f"{settings.comparison_extraction_timeout_seconds}s"
        )
        logger.error(f"Comparison fact extraction failed: {error_message}")
        ApiLogDB().insert_log(
            purpose="comparison_extraction",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata={"retrieved_chunks": len(citations)},
            error_message=error_message,
        )
        return []
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {str(exc) or repr(exc)}"
        logger.error(f"Comparison fact extraction failed: {error_message}")
        ApiLogDB().insert_log(
            purpose="comparison_extraction",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata={"retrieved_chunks": len(citations)},
            error_message=error_message,
        )
        return []


def normalize_comparison_value(value, unit: str | None = None) -> float | None:
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if unit == "%" or number > 1:
        return number / 100

    return number


def rank_comparison_facts(question: str, facts: list[dict]) -> list[dict]:
    question_lower = question.lower()
    lower_is_better = any(term in question_lower for term in LOWER_IS_BETTER_TERMS)
    ranked = []

    for fact in facts:
        value = normalize_comparison_value(fact.get("value"), fact.get("unit"))
        if value is None:
            continue

        ranked.append(
            {
                **fact,
                "normalized_value": value,
            }
        )

    return sorted(
        ranked,
        key=lambda item: item["normalized_value"],
        reverse=not lower_is_better,
    )


async def generate_comparison_answer(
    question: str,
    citations: list[Citation],
    ranked_facts: list[dict],
    conversation_history: str,
    user_id: str,
    document_id: str,
    session_id: str,
) -> tuple[str, str]:
    facts_text = json.dumps(ranked_facts, indent=2)
    context = format_context(citations)
    prompt = (
        "Answer the user's comparison or ranking question using only the ranked facts "
        "and document context below. State the top-ranked item/value, explain the "
        "comparison briefly, and cite page numbers. If facts are incomplete, say what "
        "is missing. Keep the answer generic to the document domain.\n\n"
        f"Previous conversation:\n{conversation_history or 'None'}\n\n"
        f"Question:\n{question}\n\n"
        f"Ranked facts:\n{facts_text or '[]'}\n\n"
        f"Document context:\n{context}"
    )
    started_at = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=settings.comparison_answer_timeout_seconds) as client:
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
                    "messages": [{"role": "user", "content": prompt}],
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
            purpose="comparison_answer",
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
            request_metadata={
                "retrieved_chunks": len(citations),
                "ranked_facts": len(ranked_facts),
                "context_char_count": len(context),
            },
            response_metadata={"answer_length": len(answer), "usage_raw": usage},
            response_content=answer,
            raw_response=data,
        )
        return answer, settings.opencode_model
    except httpx.HTTPStatusError as exc:
        error_message = f"{exc.response.status_code} {exc.response.text}"
        logger.error(f"Comparison answer generation failed: {error_message}")
        ApiLogDB().insert_log(
            purpose="comparison_answer",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata={"retrieved_chunks": len(citations), "ranked_facts": len(ranked_facts)},
            raw_response={
                "status_code": exc.response.status_code,
                "body": exc.response.text,
            },
            error_message=error_message,
        )
        raise RuntimeError("LLM call failed. Please try again later.") from exc
    except httpx.TimeoutException as exc:
        error_message = (
            f"{type(exc).__name__}: comparison answer exceeded "
            f"{settings.comparison_answer_timeout_seconds}s"
        )
        logger.error(f"Comparison answer generation failed: {error_message}")
        ApiLogDB().insert_log(
            purpose="comparison_answer",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata={"retrieved_chunks": len(citations), "ranked_facts": len(ranked_facts)},
            error_message=error_message,
        )
        raise RuntimeError("LLM call failed. Please try again later.") from exc
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {str(exc) or repr(exc)}"
        logger.error(f"Comparison answer generation failed: {error_message}")
        ApiLogDB().insert_log(
            purpose="comparison_answer",
            model=settings.opencode_model,
            status="error",
            user_id=user_id,
            document_id=document_id,
            session_id=session_id,
            user_prompt=question,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            request_metadata={"retrieved_chunks": len(citations), "ranked_facts": len(ranked_facts)},
            error_message=error_message,
        )
        raise RuntimeError("LLM call failed. Please try again later.") from exc
