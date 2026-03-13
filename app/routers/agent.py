"""
Agent API router.

Exposes a single endpoint that runs the full Toolhouse-powered PhysioBot
agentic loop: demonstrate → record → evaluate → speak, all orchestrated by
Claude claude-sonnet-4-6 via Toolhouse.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app import session as session_store
from app.agent import physiobot_agent

logger = logging.getLogger(__name__)
router = APIRouter()


class AgentRunRequest(BaseModel):
    exercise_name: str = "shoulder_rotation"


class AgentRunResponse(BaseModel):
    session_id: str
    exercise_name: str
    status: str
    message: str


class AgentResultResponse(BaseModel):
    session_id: str
    phase: str
    score: int | None = None
    is_correct: bool | None = None
    feedback: str | None = None
    corrections: list[str] = []


@router.post("/run", response_model=AgentRunResponse)
async def run_agent_session(
    body: AgentRunRequest,
    background_tasks: BackgroundTasks,
) -> AgentRunResponse:
    """
    Start a fully autonomous PhysioBot session powered by the Toolhouse agent.

    The agent loop runs in the background. Poll GET /api/agent/{session_id}/result
    to check completion and retrieve the evaluation.
    """
    session = session_store.create_session(body.exercise_name)
    session_id = session.session_id

    async def _run() -> None:
        try:
            await physiobot_agent.run_session(session_id, body.exercise_name)
        except Exception as exc:  # noqa: BLE001
            logger.error("Agent session %s failed: %s", session_id, exc)
            try:
                session_store.update_phase(session_id, "error")
            except KeyError:
                pass

    background_tasks.add_task(_run)

    return AgentRunResponse(
        session_id=session_id,
        exercise_name=body.exercise_name,
        status="started",
        message=(
            f"Agent session started for '{body.exercise_name}'. "
            f"Poll GET /api/agent/{session_id}/result to track progress."
        ),
    )


@router.get("/{session_id}/result", response_model=AgentResultResponse)
async def get_agent_result(session_id: str) -> AgentResultResponse:
    """
    Return the current state and evaluation result of an agent session.

    While the agent is still running, score/feedback will be null.
    Once phase is 'feedback', the full evaluation is available.
    """
    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    base = AgentResultResponse(session_id=session_id, phase=session.phase)

    if session.history:
        last = session.history[-1].evaluation
        base.score = last.get("score")
        base.is_correct = last.get("is_correct")
        base.feedback = last.get("feedback")
        base.corrections = last.get("corrections", [])

    return base
