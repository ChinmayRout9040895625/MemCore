"""Phase 9 — SDK pure logic: retry policy, backoff, error mapping."""

import pytest

from memcore.sdk._shared import (
    RETRYABLE_STATUSES,
    RetryPolicy,
    compute_backoff,
    error_from_response,
    is_retryable,
)
from memcore.sdk.exceptions import (
    APIError,
    AuthError,
    ConflictError,
    NotFoundError,
    ServerError,
    ValidationAPIError,
)
from memcore.sdk.models import Job


class TestBackoff:
    def test_exponential_progression(self) -> None:
        policy = RetryPolicy()
        assert compute_backoff(0, policy) == pytest.approx(0.2)
        assert compute_backoff(1, policy) == pytest.approx(0.4)
        assert compute_backoff(2, policy) == pytest.approx(0.8)

    def test_capped(self) -> None:
        policy = RetryPolicy(backoff_base=1.0, backoff_cap=3.0)
        assert compute_backoff(10, policy) == 3.0

    def test_policy_is_frozen(self) -> None:
        with pytest.raises(AttributeError):
            RetryPolicy().max_attempts = 5  # type: ignore[misc]


class TestRetryability:
    def test_get_retries_transient_statuses(self) -> None:
        for status in sorted(RETRYABLE_STATUSES):
            assert is_retryable("GET", status)
        assert is_retryable("get", 503)  # case-insensitive

    def test_get_retries_transport_failure(self) -> None:
        assert is_retryable("GET", None)

    def test_get_does_not_retry_client_errors(self) -> None:
        for status in (400, 401, 404, 409, 422):
            assert not is_retryable("GET", status)

    def test_non_idempotent_methods_never_retry(self) -> None:
        for method in ("POST", "PATCH", "DELETE", "PUT"):
            assert not is_retryable(method, 503)
            assert not is_retryable(method, None)


class TestErrorMapping:
    def test_status_specific_classes(self) -> None:
        cases = [(401, AuthError), (404, NotFoundError), (409, ConflictError),
                 (422, ValidationAPIError), (500, ServerError), (503, ServerError)]
        for status, expected in cases:
            error = error_from_response(status, {"title": "T", "detail": "D"})
            assert type(error) is expected
            assert error.status == status
            assert error.title == "T"
            assert error.detail == "D"

    def test_unknown_4xx_is_plain_api_error(self) -> None:
        error = error_from_response(418, {"title": "teapot", "detail": "no"})
        assert type(error) is APIError

    def test_tolerates_missing_payload(self) -> None:
        error = error_from_response(404, None)
        assert error.detail == "HTTP 404"
        assert "404" in str(error)


class TestJobModel:
    def test_done_states(self) -> None:
        assert Job(job_id="j", state="succeeded").done
        assert Job(job_id="j", state="failed").done
        assert not Job(job_id="j", state="pending").done
        assert not Job(job_id="j", state="running").done
