from app.state_machine import can_transition


def test_week4_state_machine_allows_retry_and_cancel_flow():
    assert can_transition("PENDING", "RUNNING")
    assert can_transition("RUNNING", "RETRYING")
    assert can_transition("RETRYING", "PENDING")
    assert can_transition("RUNNING", "CANCELING")
    assert can_transition("CANCELING", "CANCELED")


def test_week4_state_machine_rejects_terminal_and_skip_transitions():
    assert not can_transition("SUCCESS", "RUNNING")
    assert not can_transition("PENDING", "SUCCESS")
    assert not can_transition("RUNNING", "CANCELED")

