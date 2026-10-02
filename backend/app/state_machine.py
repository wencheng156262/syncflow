"""Job status definitions and legal transitions for Week 4."""

from typing import FrozenSet


ALL_STATUSES: FrozenSet[str] = frozenset(
    {
        "PENDING",
        "RUNNING",
        "RETRYING",
        "SUCCESS",
        "PARTIAL_SUCCESS",
        "FAILED",
        "CANCELING",
        "CANCELED",
    }
)

TERMINAL_STATUSES: FrozenSet[str] = frozenset(
    {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "CANCELED"}
)

TRANSITIONS = {
    "PENDING": frozenset({"RUNNING", "CANCELED"}),
    "RUNNING": frozenset({"SUCCESS", "PARTIAL_SUCCESS", "RETRYING", "FAILED", "CANCELING"}),
    "RETRYING": frozenset({"PENDING", "FAILED", "CANCELED"}),
    "CANCELING": frozenset({"CANCELED", "FAILED"}),
    "SUCCESS": frozenset(),
    "PARTIAL_SUCCESS": frozenset(),
    "FAILED": frozenset(),
    "CANCELED": frozenset(),
}


def can_transition(current_status: str, next_status: str) -> bool:
    return next_status in TRANSITIONS.get(current_status, frozenset())

