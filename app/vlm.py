"""
VLM (Vision Language Model) evaluation module.

Sends captured exercise frames to Claude claude-sonnet-4-6 (via Anthropic) and receives
a structured physiotherapy assessment: score, qualitative feedback, and corrections.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-exercise evaluation criteria sent to the VLM
# ---------------------------------------------------------------------------
EXERCISE_CRITERIA: dict[str, str] = {
    "shoulder_rotation": (
        "The patient should perform a full, smooth circular rotation of the shoulder. "
        "Key points to assess:\n"
        "1. Full range of motion — arm reaches above the head and sweeps forward and back.\n"
        "2. Elbow remains straight throughout the arc.\n"
        "3. Movement is slow and controlled, not jerky.\n"
        "4. Both shoulders remain level (no compensatory shrugging).\n"
        "5. Core is stable — no trunk lean or excessive body sway."
    ),
    "elbow_flex": (
        "The patient should perform elbow flexion and extension (bicep curl motion). "
        "Key points to assess:\n"
        "1. Full range of motion — elbow fully extends at bottom, forearm reaches shoulder height at top.\n"
        "2. Upper arm remains stationary against the body — no swinging.\n"
        "3. Wrist is neutral (not curled or extended) throughout.\n"
        "4. Movement is smooth and controlled on both the up and down phase.\n"
        "5. Symmetry if performing bilaterally — both arms moving together."
    ),
    "wrist_rotation": (
        "The patient should perform wrist pronation and supination (palm up / palm down). "
        "Key points to assess:\n"
        "1. Full range of motion — palm fully faces up then fully faces down.\n"
        "2. Elbow remains bent at ~90° and fixed against the side.\n"
        "3. Only the forearm rotates — no elbow or shoulder compensation.\n"
        "4. Movement is slow and deliberate, with a brief pause at each end.\n"
        "5. No pain-guarding behaviour (sudden stops, grimacing, protective posture)."
    ),
}

SYSTEM_PROMPT = (
    "You are a certified physiotherapy AI assistant evaluating a patient's exercise form "
    "from a sequence of video frames. Your role is to provide clear, encouraging, and "
    "clinically accurate feedback that helps the patient improve their rehabilitation.\n\n"
    "Always respond with a JSON object in exactly this schema:\n"
    "{\n"
    '  "score": <integer 0-10>,\n'
    '  "is_correct": <boolean — true if score >= 7>,\n'
    '  "feedback": "<one encouraging sentence summarising overall performance>",\n'
    '  "corrections": ["<specific correction 1>", "<specific correction 2>", ...]\n'
    "}\n\n"
    "corrections should be an empty list if the form is good. "
    "Be specific and actionable — say exactly what to change and how. "
    "Respond ONLY with the JSON object, no markdown fences or extra text."
)


class VLMEvaluator:
    """Sends exercise frames to Claude claude-sonnet-4-6 vision and parses structured feedback."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def evaluate_exercise(
        self,
        frames_b64: list[str],
        exercise_name: str,
        criteria: str | None = None,
    ) -> dict[str, Any]:
        """
        Evaluate a patient's exercise performance from a list of base64 frames.

        Uses Claude claude-sonnet-4-6 via the Anthropic API with vision support.

        Args:
            frames_b64: List of base64-encoded JPEG frames (already sub-sampled).
            exercise_name: Key matching EXERCISE_CRITERIA (e.g. "shoulder_rotation").
            criteria: Optional override for the evaluation criteria string.

        Returns:
            Dict with keys: score (int), is_correct (bool), feedback (str),
            corrections (list[str]).

        Raises:
            ValueError: If frames_b64 is empty.
            anthropic.APIError: On API failure.
        """
        if not frames_b64:
            raise ValueError("No frames provided for VLM evaluation.")

        resolved_criteria = criteria or EXERCISE_CRITERIA.get(
            exercise_name,
            "Evaluate overall exercise form and range of motion.",
        )

        # Build the user content block: text prompt + image frames
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"Exercise: {exercise_name.replace('_', ' ').title()}\n\n"
                    f"Evaluation criteria:\n{resolved_criteria}\n\n"
                    f"The following {len(frames_b64)} frames show the patient performing "
                    "this exercise. Please evaluate their form and return your JSON assessment."
                ),
            }
        ]

        for b64 in frames_b64:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": b64,
                    },
                }
            )

        logger.info(
            "Sending %d frames to Claude claude-sonnet-4-6 for '%s' evaluation", len(frames_b64), exercise_name
        )

        # Anthropic SDK is synchronous; run in executor so we don't block the event loop
        import asyncio

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            ),
        )

        raw = response.content[0].text if response.content else "{}"
        logger.debug("VLM raw response: %s", raw)

        # Strip markdown fences if model included them despite instructions
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result: dict[str, Any] = json.loads(raw)

        # Normalise / fill missing fields defensively
        score = int(result.get("score", 0))
        result["score"] = max(0, min(10, score))
        result.setdefault("is_correct", result["score"] >= 7)
        result.setdefault("feedback", "Evaluation complete.")
        result.setdefault("corrections", [])

        logger.info(
            "Evaluation result — score=%d, is_correct=%s, corrections=%d",
            result["score"],
            result["is_correct"],
            len(result["corrections"]),
        )
        return result

    def build_spoken_feedback(self, evaluation: dict[str, Any]) -> str:
        """
        Convert a structured evaluation dict into a natural spoken sentence
        suitable for TTS delivery.

        Args:
            evaluation: Output of evaluate_exercise().

        Returns:
            A single, patient-friendly string for TTS.
        """
        feedback = evaluation.get("feedback", "")
        corrections: list[str] = evaluation.get("corrections", [])
        score: int = evaluation.get("score", 0)

        if not corrections:
            return f"Excellent work! {feedback} Your score is {score} out of 10. Keep it up!"

        correction_text = ". ".join(corrections[:2])  # speak first 2 corrections
        return (
            f"{feedback} "
            f"Your score is {score} out of 10. "
            f"Here are some things to improve: {correction_text}."
        )


# Module-level singleton
vlm_evaluator = VLMEvaluator()
