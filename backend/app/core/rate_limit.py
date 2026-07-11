"""
Basic per-user rate limiting.

A sliding-window counter keyed by the authenticated user_id. Intended to cap
abuse and runaway LLM cost on the expensive endpoints, not to be a precise
quota system.

Caveat: state is in-process. Under multiple Modal containers each maintains its
own window, so the effective limit is roughly `limit x container_count`. That's
acceptable for a basic guard; a shared store (Redis) would be the next step if
precise global limits are needed.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_user_id

_lock = Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def _check(user_id: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        timestamps = _hits[user_id]
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

        if len(timestamps) >= limit:
            retry_after = int(timestamps[0] + window_seconds - now) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down and try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )

        timestamps.append(now)


def rate_limiter(limit: int, window_seconds: int = 60):
    """
    Build a FastAPI dependency that enforces `limit` requests per window per user.
    Returns the user_id so routes can keep using it directly.
    """

    async def dependency(user_id: str = Depends(get_current_user_id)) -> str:
        _check(user_id, limit, window_seconds)
        return user_id

    return dependency


def reset_rate_limits() -> None:
    """Clear all counters (used by tests)."""
    with _lock:
        _hits.clear()
