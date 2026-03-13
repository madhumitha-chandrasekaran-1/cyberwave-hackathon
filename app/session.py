"""
Rehabilitation session state management.

Uses an in-memory dict — perfectly adequate for a hackathon.
Replace with Redis or a DB for production.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
Phase = Literal["idle", "demonstrating", "recording", "evaluating", "feedback", "complete"]


@dataclass
class AttemptRecord:
    """Stores the result of one patient attempt at an exercise."""

    attempt_number: int
    timestamp: str
    frame_count: int
    evaluation: dict[str, Any]


@dataclass
class RehabSession:
    """All state for a single rehabilitation session."""

    session_id: str
    exercise_name: str
    phase: Phase = "idle"
    attempt_count: int = 0
    history: list[AttemptRecord] = field(default_factory=list)
    cyberwave_run_id: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict for API responses."""
        return {
            "session_id": self.session_id,
            "exercise_name": self.exercise_name,
            "phase": self.phase,
            "attempt_count": self.attempt_count,
            "cyberwave_run_id": self.cyberwave_run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": [
                {
                    "attempt_number": a.attempt_number,
                    "timestamp": a.timestamp,
                    "frame_count": a.frame_count,
                    "evaluation": a.evaluation,
                }
                for a in self.history
            ],
        }


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
_sessions: dict[str, RehabSession] = {}


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def create_session(exercise_name: str) -> RehabSession:
    """
    Create a new RehabSession and persist it in the store.

    Args:
        exercise_name: The exercise the patient will perform.

    Returns:
        The newly created RehabSession.
    """
    session_id = str(uuid.uuid4())
    session = RehabSession(session_id=session_id, exercise_name=exercise_name)
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> RehabSession | None:
    """
    Retrieve a session by ID.

    Args:
        session_id: UUID string.

    Returns:
        RehabSession or None if not found.
    """
    return _sessions.get(session_id)


def update_phase(session_id: str, phase: Phase) -> RehabSession:
    """
    Update the phase of an existing session.

    Args:
        session_id: Target session UUID.
        phase: New phase value.

    Returns:
        Updated RehabSession.

    Raises:
        KeyError: If session_id does not exist.
    """
    session = _sessions[session_id]
    session.phase = phase
    session.updated_at = datetime.now(timezone.utc).isoformat()
    return session


def record_attempt(
    session_id: str,
    frame_count: int,
    evaluation: dict[str, Any],
) -> RehabSession:
    """
    Append an attempt result to the session history.

    Args:
        session_id: Target session UUID.
        frame_count: Number of camera frames captured.
        evaluation: VLM evaluation dict.

    Returns:
        Updated RehabSession.

    Raises:
        KeyError: If session_id does not exist.
    """
    session = _sessions[session_id]
    session.attempt_count += 1
    attempt = AttemptRecord(
        attempt_number=session.attempt_count,
        timestamp=datetime.now(timezone.utc).isoformat(),
        frame_count=frame_count,
        evaluation=evaluation,
    )
    session.history.append(attempt)
    session.updated_at = datetime.now(timezone.utc).isoformat()
    return session


def delete_session(session_id: str) -> bool:
    """
    Remove a session from the store.

    Args:
        session_id: Target session UUID.

    Returns:
        True if removed, False if it did not exist.
    """
    return _sessions.pop(session_id, None) is not None


def list_sessions() -> list[dict[str, Any]]:
    """Return a summary list of all active sessions."""
    return [s.to_dict() for s in _sessions.values()]
