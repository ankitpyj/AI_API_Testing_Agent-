"""
Gemini API Retry Helper.

Provides resilient retry handling with exponential backoff, jitter,
Retry-After header support, and strict transient vs. permanent error classification.

Transient errors (retried up to max_retries):
  - HTTP 503 (Unavailable / High Demand)
  - HTTP 429 (Rate Limit / Resource Exhausted)
  - HTTP 502 / 504 (Bad Gateway / Gateway Timeout)
  - Timeouts (APITimeoutError, TimeoutError, socket timeouts)
  - Connection errors (APIConnectionError, ConnectionError, network drop)

Permanent errors (fail immediately, never retried):
  - HTTP 400 (Bad Request / Invalid Argument)
  - HTTP 401 (Unauthorized / Invalid API Key)
  - HTTP 403 (Forbidden / Permission Denied)
  - HTTP 404 (Not Found / Model Not Found)
  - HTTP 422 (Unprocessable Entity)
"""

import logging
import random
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# HTTP status codes that represent transient, retryable server-side conditions
TRANSIENT_STATUS_CODES = {429, 502, 503, 504}

# HTTP status codes that represent permanent client or authorization errors
PERMANENT_STATUS_CODES = {400, 401, 403, 404, 422}


def is_transient_error(exc: Exception) -> bool:
    """
    Determine if an exception represents a transient, retryable condition.

    Returns True for temporary spikes (503), rate limits (429), timeouts,
    and connection drops.
    Returns False for permanent client/auth errors (400, 401, 403, 404, 422).
    """
    if exc is None:
        return False

    # 1. Check HTTP status code if present on the exception object
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        try:
            status_code = int(status_code)
            if status_code in PERMANENT_STATUS_CODES:
                return False
            if status_code in TRANSIENT_STATUS_CODES:
                return True
            if status_code >= 500:
                return True
        except (ValueError, TypeError):
            pass

    # 2. Check standard Python built-in exception classes
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True

    # 3. Check OpenAI / HTTP client exception class names
    exc_class_name = type(exc).__name__
    if any(perm in exc_class_name for perm in (
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "BadRequestError",
        "UnprocessableEntityError",
    )):
        return False

    if any(trans in exc_class_name for trans in (
        "RateLimitError",
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
    )):
        return True

    # 4. Fallback: inspect exception string content for transient indicators
    # (Safe diagnostic inspection without logging sensitive key material)
    msg = str(exc).lower()
    permanent_indicators = [
        "401", "unauthorized", "api_key", "invalid api key",
        "403", "permission_denied",
        "404", "not_found", "model not found",
        "400", "invalid_argument",
    ]
    if any(indicator in msg for indicator in permanent_indicators):
        return False

    transient_indicators = [
        "503", "high demand", "temporarily unavailable",
        "try again later", "spikes in demand",
        "429", "resource_exhausted", "quota",
        "timeout", "timed out",
        "connection", "connection reset", "connection refused",
    ]
    if any(indicator in msg for indicator in transient_indicators):
        return True

    return False


def extract_retry_after(exc: Exception) -> Optional[float]:
    """
    Extract the 'Retry-After' duration in seconds from exception headers if available.
    Returns None if absent or invalid.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None

    headers = getattr(response, "headers", None)
    if not headers or not hasattr(headers, "get"):
        return None

    retry_after_raw = headers.get("retry-after") or headers.get("Retry-After")
    if not retry_after_raw:
        return None

    try:
        val = float(retry_after_raw)
        if val > 0:
            return val
    except (ValueError, TypeError):
        pass

    return None


def execute_with_retry(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    jitter_range: tuple = (0.1, 0.5),
    caller_name: str = "Gemini",
    **kwargs: Any,
) -> Any:
    """
    Execute a callable with bounded exponential backoff and jitter.

    Retry schedule:
      - Attempt 1: immediate execution
      - Attempt 2: after ~2s (base_delay * 1 + jitter, or Retry-After)
      - Attempt 3: after ~4s (base_delay * 2 + jitter, or Retry-After)

    Permanent errors (401, 403, 404, etc.) are raised immediately without retrying.
    Transient errors (503, 429, timeout, connection) are retried up to max_retries.
    """
    last_exception: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exception = exc
            exc_type = type(exc).__name__
            is_transient = is_transient_error(exc)

            if not is_transient:
                logger.warning(
                    "[%s] Permanent error encountered on attempt %d/%d (%s). "
                    "Skipping retries.",
                    caller_name,
                    attempt,
                    max_retries,
                    exc_type,
                )
                raise exc

            if attempt >= max_retries:
                logger.error(
                    "[%s] All %d attempts failed. Final error: %s: %s",
                    caller_name,
                    max_retries,
                    exc_type,
                    str(exc),
                )
                raise exc

            # Calculate delay with exponential factor and Retry-After header
            retry_after = extract_retry_after(exc)
            step_delay = base_delay * attempt
            if retry_after is not None and retry_after > 0:
                delay = max(step_delay, retry_after)
            else:
                delay = step_delay

            # Apply random jitter
            delay += random.uniform(jitter_range[0], jitter_range[1])
            delay = min(delay, max_delay)

            logger.info(
                "[%s] Transient error on attempt %d/%d (%s). "
                "Retrying in %.2fs...",
                caller_name,
                attempt,
                max_retries,
                exc_type,
                delay,
            )
            time.sleep(delay)

    # Should not reach here, but re-raise if it does
    if last_exception:
        raise last_exception
