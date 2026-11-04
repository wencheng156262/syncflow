"""Retry classification and backoff rules for Week 5 task execution."""

from typing import Iterable, Tuple


DEFAULT_BACKOFF_SECONDS: Tuple[int, ...] = (5, 30, 120)

# Validation and user-control errors are deterministic and must not be retried.
NON_RETRYABLE_ERROR_CODES = frozenset(
    {
        "CSV_HEADER_INVALID",
        "FILE_EMPTY",
        "FILE_ENCODING_INVALID",
        "FILE_UNREADABLE",
        "FILE_TOO_MANY_ROWS",
        "ROW_COLUMN_COUNT_MISMATCH",
        "FIELD_REQUIRED",
        "EXTERNAL_ID_INVALID",
        "EXTERNAL_ID_DUPLICATE",
        "NAME_TOO_LONG",
        "AMOUNT_INVALID",
        "DATE_INVALID",
        "JOB_CANCELED",
        "JOB_NOT_FOUND",
        "IDEMPOTENCY_KEY_CONFLICT",
    }
)


def is_retryable_error(error_code: str) -> bool:
    """Return whether an error may be retried by the Worker."""

    return error_code not in NON_RETRYABLE_ERROR_CODES


def backoff_seconds(retry_number: int, schedule: Iterable[int] = DEFAULT_BACKOFF_SECONDS) -> int:
    """Return the delay before the requested retry, reusing the last delay after the schedule ends."""

    delays = tuple(schedule)
    if retry_number <= 0 or not delays:
        return 0
    return delays[min(retry_number - 1, len(delays) - 1)]


def parse_backoff_schedule(raw_value: str) -> Tuple[int, ...]:
    """Parse a comma-separated non-negative retry schedule from an environment variable."""

    values = []
    for raw_item in raw_value.split(","):
        item = raw_item.strip()
        if item:
            values.append(max(int(item), 0))
    return tuple(values) or DEFAULT_BACKOFF_SECONDS
