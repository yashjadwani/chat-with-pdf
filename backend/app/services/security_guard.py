"""
Input security guard for chat questions.

A fast, deterministic pre-filter that runs before retrieval / the LLM. It does
two things from an AI-security standpoint:

  1. BLOCK obvious prompt-injection / jailbreak attempts (e.g. "ignore previous
     instructions", "reveal your system prompt"). These are attacks, not
     legitimate document questions, so they are refused without an LLM call.

  2. FLAG questions that request personal or sensitive information (IDs,
     financial, contact, health, credentials). These are *allowed* — the data
     may legitimately be in the user's own document — but are labelled so the
     caller can log/audit them, and the hardened system prompt handles masking.

This is a defense-in-depth layer, not a complete solution: pattern matching can
be evaded by clever phrasing, and it deliberately does not block personal-data
questions (that would break legitimate use). Pair it with the prompt hardening
in llm.py and, for higher assurance, an LLM/classifier-based check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REFUSAL_MESSAGE = (
    "I can't help with that request. I can only answer questions about the "
    "content of your uploaded document."
)


@dataclass(frozen=True)
class GuardVerdict:
    action: str  # "block" | "flag" | "allow"
    category: str | None = None  # "prompt_injection" | "personal_data" | None
    reason: str | None = None


_INJECTION_PATTERNS = [
    re.compile(p)
    for p in (
        r"ignore (?:all |any |the |your )*(?:previous|prior|above|earlier|preceding) "
        r"(?:instructions|instruction|prompts?|messages?|rules|directions)",
        r"disregard (?:all |the |any |your )*(?:previous|prior|above|earlier|system|safety)",
        r"forget (?:all |your |the )*(?:previous|prior|above|earlier) (?:instructions|rules)",
        r"(?:reveal|show|print|repeat|display|expose|leak) (?:me )?(?:your |the |these )*"
        r"(?:system prompt|system message|initial prompt|original prompt|"
        r"(?:your|these|the) instructions|prompt above)",
        r"what (?:are|is|were) your (?:system )?(?:instructions|prompt|rules)",
        r"\b(?:developer mode|jailbreak|dan mode)\b",
        r"you are (?:now )?(?:dan\b|in developer mode|jailbroken|an unrestricted|an uncensored)",
        r"(?:bypass|override|turn off|disable|ignore) (?:your |the |all )*"
        r"(?:rules|restrictions|guidelines|safety|filters?|guardrails?|policies)",
        r"(?:pretend|act) (?:you are|to be|as)(?: an?)? (?:unrestricted|uncensored|dan\b)",
    )
]

_PERSONAL_DATA_PATTERNS = [
    re.compile(p)
    for p in (
        r"\b(?:social security|ssn)\b",
        r"\bnational insurance (?:number|no)\b",
        r"\bpassport (?:number|no|details)\b",
        r"\b(?:credit|debit) card\b|\bcard number\b|\bcvv\b",
        r"\bbank account\b|\brouting number\b|\bsort code\b|\biban\b",
        r"\b(?:home|residential|postal) address\b",
        r"\bdate of birth\b|\bdob\b",
        r"\b(?:phone|mobile|cell|contact) number\b",
        r"\bemail address(?:es)? (?:of|for)\b",
        r"\bpersonal (?:details|information|data|info)\b",
        r"\b(?:password|passwords|api[ _-]?key|secret key|private key|access token|credentials)\b",
        r"\bmedical (?:record|history|condition)\b|\bhealth record\b",
    )
]


def check_question(question: str) -> GuardVerdict:
    """Classify a user question before it reaches retrieval / the LLM."""
    text = question.lower()

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return GuardVerdict(
                action="block",
                category="prompt_injection",
                reason="Possible prompt-injection or jailbreak attempt.",
            )

    for pattern in _PERSONAL_DATA_PATTERNS:
        if pattern.search(text):
            return GuardVerdict(
                action="flag",
                category="personal_data",
                reason="Question appears to request personal or sensitive information.",
            )

    return GuardVerdict(action="allow")
