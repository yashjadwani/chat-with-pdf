import time

import pytest
from fastapi import HTTPException

from app.core.rate_limit import _check, reset_rate_limits


@pytest.fixture(autouse=True)
def _clear():
    reset_rate_limits()
    yield
    reset_rate_limits()


class TestCheck:
    def test_allows_up_to_the_limit(self):
        for _ in range(3):
            _check("user-a", limit=3, window_seconds=60)  # should not raise

    def test_blocks_the_request_over_the_limit(self):
        for _ in range(3):
            _check("user-a", limit=3, window_seconds=60)
        with pytest.raises(HTTPException) as exc_info:
            _check("user-a", limit=3, window_seconds=60)
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers

    def test_limits_are_isolated_per_user(self):
        for _ in range(3):
            _check("user-a", limit=3, window_seconds=60)
        # a different user is unaffected
        _check("user-b", limit=3, window_seconds=60)

    def test_window_expiry_frees_capacity(self):
        _check("user-a", limit=1, window_seconds=1)
        with pytest.raises(HTTPException):
            _check("user-a", limit=1, window_seconds=1)
        time.sleep(1.1)
        _check("user-a", limit=1, window_seconds=1)  # window rolled over, allowed again
