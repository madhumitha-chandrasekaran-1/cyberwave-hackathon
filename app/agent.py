"""
Toolhouse-powered PhysioBot agent.

Architecture:
  - Anthropic Claude claude-sonnet-4-6 is the LLM brain.
  - Toolhouse manages tool execution (cloud tools + local tools registered here).
  - Local tools give Claude the ability to:
      1. Trigger the SO101 arm to demonstrate an exercise  (Cyberwave)
      2. Capture frames from the rover camera             (OpenCV)
      3. Evaluate exercise form from captured frames      (Claude vision)
      4. Convert evaluation text to speech               (Smallest.ai TTS)

Usage:
    agent = PhysiobotAgent()
    result = await agent.run_session(session_id, exercise_name)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import anthropic
from toolhouse import Provider, Toolhouse

from app import camera, session as session_store
from app.config import settings
from app.cyberwave import cyberwave_client
from app.vlm import EXERCISE_CRITERIA, SYSTEM_PROMPT, vlm_evaluator
from app.voice import text_to_speech

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """You are PhysioBot, an AI physiotherapy coaching agent.
You help patients perform rehabilitation exercises correctly using a physical robot arm and camera.

Your job for each session is to:
1. Call demonstrate_exercise to have the SO101 robot arm show the patient the movement.
2. Call capture_patient_attempt to record the patient doing the exercise.
3. Call evaluate_exercise_form to score the patient's form using computer vision.
4. Call speak_feedback to play the evaluation as voice feedback to the patient.

Be concise. Call tools in order. After speaking the feedback, summarise the session result as JSON:
{"score": <int>, "is_correct": <bool>, "feedback": "<str>", "corrections": [<str>]}
"""


class PhysiobotAgent:
    """
    Orchestrates a full physiotherapy rehabilitation session using Toolhouse.

    The agent registers four local tools that Claude can call during the
    agentic loop. Toolhouse handles the tool-call → execution → result cycle.
    """

    def __init__(self) -> None:
        self._anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._th = Toolhouse(
            api_key=settings.toolhouse_api_key,
            provider=Provider.ANTHROPIC,
        )
        self._register_tools()

    # ------------------------------------------------------------------
    # Local tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        """Register all PhysioBot local tools with the Toolhouse SDK."""

        @self._th.register_local_tool("demonstrate_exercise")
        def demonstrate_exercise(exercise_name: str) -> str:
            """
            Trigger the SO101 robot arm to demonstrate an exercise motion.
            Returns a status message.
            """
            logger.info("[tool] demonstrate_exercise(%s)", exercise_name)
            # Run the async cyberwave call synchronously inside the tool
            try:
                result = asyncio.get_event_loop().run_until_complete(
                    cyberwave_client.demonstrate_exercise(exercise_name)
                )
                run_id = result.get("run_id", "unknown")
                return f"Arm demonstration started for '{exercise_name}'. Cyberwave run_id={run_id}."
            except Exception as exc:  # noqa: BLE001
                logger.warning("Cyberwave unavailable: %s", exc)
                return f"Arm demo triggered (Cyberwave offline in dev mode): {exc}"

        @self._th.register_local_tool("capture_patient_attempt")
        def capture_patient_attempt(session_id: str, duration_seconds: int = 10) -> str:
            """
            Record the patient performing the exercise for the given duration.
            Uses the rover camera via OpenCV. Returns how many frames were captured.
            """
            logger.info("[tool] capture_patient_attempt(session=%s, dur=%ds)", session_id, duration_seconds)
            try:
                frames = asyncio.get_event_loop().run_until_complete(
                    camera.capture_frames_async(session_id, duration_seconds=duration_seconds)
                )
                session_store.update_phase(session_id, "evaluating")
                return f"Captured {len(frames)} frames over {duration_seconds}s for session {session_id}."
            except Exception as exc:  # noqa: BLE001
                logger.error("Camera capture failed: %s", exc)
                return f"Camera capture failed: {exc}"

        @self._th.register_local_tool("evaluate_exercise_form")
        def evaluate_exercise_form(session_id: str, exercise_name: str) -> str:
            """
            Retrieve cached camera frames for the session and evaluate the patient's
            exercise form using Claude vision. Returns a JSON evaluation string.
            """
            logger.info("[tool] evaluate_exercise_form(session=%s, exercise=%s)", session_id, exercise_name)
            frames = camera.get_stored_frames(session_id)
            if not frames:
                return json.dumps({"error": "No frames found. Call capture_patient_attempt first."})

            frames_b64 = camera.frames_to_base64_list(
                frames, sample_every=settings.vlm_frame_sample_every
            )

            try:
                evaluation = asyncio.get_event_loop().run_until_complete(
                    vlm_evaluator.evaluate_exercise(
                        frames_b64=frames_b64,
                        exercise_name=exercise_name,
                    )
                )
                session_store.record_attempt(session_id, len(frames), evaluation)
                camera.clear_stored_frames(session_id)
                session_store.update_phase(session_id, "feedback")
                return json.dumps(evaluation)
            except Exception as exc:  # noqa: BLE001
                logger.error("VLM evaluation failed: %s", exc)
                return json.dumps({"error": str(exc)})

        @self._th.register_local_tool("speak_feedback")
        def speak_feedback(text: str) -> str:
            """
            Convert the given feedback text to speech using Smallest.ai TTS
            and save the audio to the session. Returns confirmation.
            """
            logger.info("[tool] speak_feedback(text='%s...')", text[:60])
            try:
                audio_bytes = asyncio.get_event_loop().run_until_complete(
                    text_to_speech(text)
                )
                # Store in a simple module-level cache so the /speak endpoint can serve it
                _audio_cache[text[:64]] = audio_bytes
                return f"Speech generated successfully ({len(audio_bytes)} bytes)."
            except Exception as exc:  # noqa: BLE001
                logger.error("TTS failed: %s", exc)
                return f"TTS failed (check SMALLEST_API_KEY): {exc}"

    # ------------------------------------------------------------------
    # Tool schemas for Anthropic
    # ------------------------------------------------------------------

    def _local_tool_schemas(self) -> list[dict[str, Any]]:
        """Return Anthropic-format tool schemas for the four local tools."""
        return [
            {
                "name": "demonstrate_exercise",
                "description": "Trigger the SO101 robot arm to demonstrate an exercise motion to the patient.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "exercise_name": {
                            "type": "string",
                            "description": "Exercise key: 'shoulder_rotation', 'elbow_flex', or 'wrist_rotation'.",
                        }
                    },
                    "required": ["exercise_name"],
                },
            },
            {
                "name": "capture_patient_attempt",
                "description": "Record the patient performing the exercise using the rover camera.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Active session ID."},
                        "duration_seconds": {
                            "type": "integer",
                            "description": "How many seconds to record. Default 10.",
                            "default": 10,
                        },
                    },
                    "required": ["session_id"],
                },
            },
            {
                "name": "evaluate_exercise_form",
                "description": "Analyse captured frames and score the patient's exercise form using Claude vision.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Active session ID."},
                        "exercise_name": {
                            "type": "string",
                            "description": "Exercise key matching what was captured.",
                        },
                    },
                    "required": ["session_id", "exercise_name"],
                },
            },
            {
                "name": "speak_feedback",
                "description": "Convert evaluation feedback text to spoken audio via Smallest.ai TTS.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Feedback text to speak aloud."}
                    },
                    "required": ["text"],
                },
            },
        ]

    # ------------------------------------------------------------------
    # Main agentic loop
    # ------------------------------------------------------------------

    async def run_session(self, session_id: str, exercise_name: str) -> dict[str, Any]:
        """
        Run a full physiotherapy session as an agentic loop.

        Claude decides which tools to call and in what order, Toolhouse
        executes them, and the loop continues until Claude produces a final
        text response (no more tool calls).

        Args:
            session_id: Active RehabSession ID (created before calling this).
            exercise_name: The exercise to coach (e.g. "shoulder_rotation").

        Returns:
            Final evaluation dict from the session history, or an error dict.
        """
        session_store.update_phase(session_id, "demonstrating")

        criteria = EXERCISE_CRITERIA.get(exercise_name, "Evaluate overall form and range of motion.")
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"Run a physiotherapy session.\n"
                    f"Session ID: {session_id}\n"
                    f"Exercise: {exercise_name}\n"
                    f"Evaluation criteria:\n{criteria}\n\n"
                    "Please: demonstrate the exercise, capture the patient's attempt (10 seconds), "
                    "evaluate their form, and speak the feedback."
                ),
            }
        ]

        # Combine Toolhouse cloud tools with our local tool schemas
        all_tools = self._th.get_tools() + self._local_tool_schemas()

        logger.info("Agent session %s starting for exercise '%s'", session_id, exercise_name)

        # Agentic loop — continues until Claude stops calling tools
        max_iterations = 10
        for iteration in range(max_iterations):
            logger.info("Agent iteration %d/%d", iteration + 1, max_iterations)

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._anthropic.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    system=AGENT_SYSTEM_PROMPT,
                    tools=all_tools,
                    messages=messages,
                ),
            )

            logger.info("Agent stop_reason=%s", response.stop_reason)

            # Append assistant message to history
            messages.append({"role": "assistant", "content": response.content})

            # If no more tool calls, we're done
            if response.stop_reason == "end_turn":
                break

            # Execute tool calls via Toolhouse and append results
            tool_results = self._th.run_tools(response)
            messages.extend(tool_results)

        # Extract final evaluation from session history
        session = session_store.get_session(session_id)
        if session and session.history:
            last = session.history[-1]
            return last.evaluation

        # Fallback if agent didn't complete evaluation
        logger.warning("Agent session %s ended without evaluation in history", session_id)
        return {"score": 0, "is_correct": False, "feedback": "Session incomplete.", "corrections": []}


# Simple in-memory audio cache (keyed by first 64 chars of spoken text)
_audio_cache: dict[str, bytes] = {}


def get_cached_audio(text_key: str) -> bytes | None:
    """Retrieve cached TTS audio by text key prefix."""
    return _audio_cache.get(text_key[:64])


# Module-level singleton
physiobot_agent = PhysiobotAgent()
