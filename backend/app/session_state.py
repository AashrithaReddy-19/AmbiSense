from enum import StrEnum


class SessionState(StrEnum):
    CREATED="CREATED"; UPLOADING="UPLOADING"; QUEUED="QUEUED"; INITIALIZING="INITIALIZING"; PROCESSING="PROCESSING"; FINALIZING="FINALIZING"; COMPLETED="COMPLETED"; FAILED="FAILED"; STOPPING="STOPPING"; STOPPED="STOPPED"


ALLOWED = {
    SessionState.CREATED: {SessionState.UPLOADING, SessionState.QUEUED, SessionState.PROCESSING, SessionState.FAILED},
    SessionState.UPLOADING: {SessionState.QUEUED, SessionState.FAILED},
    SessionState.QUEUED: {SessionState.INITIALIZING, SessionState.FAILED},
    SessionState.INITIALIZING: {SessionState.PROCESSING, SessionState.FAILED},
    SessionState.PROCESSING: {SessionState.FINALIZING, SessionState.STOPPING, SessionState.FAILED},
    SessionState.FINALIZING: {SessionState.COMPLETED, SessionState.FAILED},
    SessionState.STOPPING: {SessionState.STOPPED, SessionState.FAILED},
    SessionState.STOPPED: {SessionState.QUEUED}, SessionState.FAILED: {SessionState.QUEUED}, SessionState.COMPLETED: set(),
}


def transition(row, target: SessionState) -> None:
    current = SessionState(row.status)
    if target != current and target not in ALLOWED[current]:
        raise ValueError(f"Invalid session transition: {current.value} -> {target.value}")
    row.status = target.value
    row.processing_stage = target.value
