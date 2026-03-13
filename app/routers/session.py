"""
Session API router.

Manages the full rehabilitation loop:
  1. Start session → trigger Cyberwave arm demo
  2. Record        → capture camera frames
  3. Evaluate      → VLM assessment
  4. Speak         → TTS feedback to patient
  5. Status        → poll current phase
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app import camera, session as session_store, vlm as vlm_module
from app.config import settings
from app.cyberwave import cyberwave_client
from app.voice import text_to_speech
from app.vlm import vlm_evaluator

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class StartSessionRequest(BaseModel):
    exercise_name: str = "shoulder_rotation"


class StartSessionResponse(BaseModel):
    session_id: str
    exercise_name: str
    phase: str
    cyberwave_run_id: str | None = None
    message: str


class RecordResponse(BaseModel):
    session_id: str
    phase: str
    message: str


class EvaluationResponse(BaseModel):
    session_id: str
    attempt_number: int
    score: int
    is_correct: bool
    feedback: str
    corrections: list[str]
    phase: str


class SpeakResponse(BaseModel):
    session_id: str
    spoken_text: str
    audio_size_bytes: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_404(session_id: str) -> session_store.RehabSession:
    s = session_store.get_session(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return s


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/start", response_model=StartSessionResponse)
async def start_session(body: StartSessionRequest) -> StartSessionResponse:
    """
    Create a new rehab session and trigger the SO101 arm to demonstrate the exercise.

    The Cyberwave call is made; if it fails (e.g. during dev without hardware)
    the session is still created and the error is logged.
    """
    session = session_store.create_session(body.exercise_name)
    logger.info("Session created: %s — exercise=%s", session.session_id, body.exercise_name)

    # Trigger arm demonstration
    cyberwave_run_id: str | None = None
    cyberwave_message = "Arm demonstration triggered."
    try:
        session_store.update_phase(session.session_id, "demonstrating")
        result = await cyberwave_client.demonstrate_exercise(body.exercise_name)
        cyberwave_run_id = result.get("run_id")
        session.cyberwave_run_id = cyberwave_run_id
    except ValueError as exc:
        # Unknown exercise — still proceed but inform caller
        cyberwave_message = f"Warning: {exc}"
        logger.warning("Cyberwave exercise lookup failed: %s", exc)
        session_store.update_phase(session.session_id, "idle")
    except Exception as exc:  # noqa: BLE001
        cyberwave_message = f"Cyberwave API unavailable — skipping arm demo. ({exc})"
        logger.error("Cyberwave trigger failed: %s", exc)
        session_store.update_phase(session.session_id, "demonstrating")

    return StartSessionResponse(
        session_id=session.session_id,
        exercise_name=session.exercise_name,
        phase=session.phase,
        cyberwave_run_id=cyberwave_run_id,
        message=cyberwave_message,
    )


@router.post("/{session_id}/record", response_model=RecordResponse)
async def record_attempt(
    session_id: str,
    background_tasks: BackgroundTasks,
    duration: int = 10,
) -> RecordResponse:
    """
    Begin recording the patient's movement for *duration* seconds (default 10).

    Recording runs in a background task so the HTTP response returns immediately.
    Poll /status to know when recording is complete.
    """
    session = _get_or_404(session_id)
    session_store.update_phase(session_id, "recording")

    async def _do_record() -> None:
        try:
            frames = await camera.capture_frames_async(session_id, duration_seconds=duration)
            logger.info(
                "Session %s: recorded %d frames", session_id, len(frames)
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Camera capture failed for session %s: %s", session_id, exc)
        finally:
            # Move to evaluating phase so frontend knows recording finished
            try:
                session_store.update_phase(session_id, "evaluating")
            except KeyError:
                pass

    background_tasks.add_task(_do_record)

    return RecordResponse(
        session_id=session_id,
        phase="recording",
        message=f"Recording started for {duration} seconds. Poll /status to check progress.",
    )


@router.post("/{session_id}/evaluate", response_model=EvaluationResponse)
async def evaluate_session(session_id: str) -> EvaluationResponse:
    """
    Retrieve cached frames from the most recent recording and send them to GPT-4o
    vision for physiotherapy assessment.
    """
    session = _get_or_404(session_id)
    session_store.update_phase(session_id, "evaluating")

    frames = camera.get_stored_frames(session_id)
    if not frames:
        raise HTTPException(
            status_code=422,
            detail="No frames found for this session. Call /record first.",
        )

    # Sub-sample frames to stay within GPT-4o token limits
    frames_b64 = camera.frames_to_base64_list(
        frames, sample_every=settings.vlm_frame_sample_every
    )

    try:
        evaluation = await vlm_evaluator.evaluate_exercise(
            frames_b64=frames_b64,
            exercise_name=session.exercise_name,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("VLM evaluation failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"VLM evaluation failed: {exc}") from exc

    # Persist to session history
    updated = session_store.record_attempt(session_id, len(frames), evaluation)
    session_store.update_phase(session_id, "feedback")
    camera.clear_stored_frames(session_id)

    return EvaluationResponse(
        session_id=session_id,
        attempt_number=updated.attempt_count,
        score=evaluation["score"],
        is_correct=evaluation["is_correct"],
        feedback=evaluation["feedback"],
        corrections=evaluation["corrections"],
        phase="feedback",
    )


@router.post("/{session_id}/speak")
async def speak_feedback(session_id: str) -> Response:
    """
    Generate TTS audio for the most recent evaluation in this session.

    Returns a WAV audio stream that the browser can play directly.
    """
    session = _get_or_404(session_id)

    if not session.history:
        raise HTTPException(
            status_code=422,
            detail="No evaluation history found. Call /evaluate first.",
        )

    latest = session.history[-1]
    spoken_text = vlm_evaluator.build_spoken_feedback(latest.evaluation)

    logger.info("TTS for session %s: '%s'", session_id, spoken_text[:80])

    try:
        audio_bytes = await text_to_speech(spoken_text)
    except Exception as exc:  # noqa: BLE001
        logger.error("TTS failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"TTS failed: {exc}") from exc

    # Determine content type — smallest.ai returns WAV by default
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'attachment; filename="feedback_{session_id}.wav"',
            "X-Spoken-Text": spoken_text[:200],  # debug header
        },
    )


@router.get("/{session_id}/status")
async def get_session_status(session_id: str) -> dict[str, Any]:
    """Return full session state including phase and attempt history."""
    session = _get_or_404(session_id)
    return session.to_dict()
