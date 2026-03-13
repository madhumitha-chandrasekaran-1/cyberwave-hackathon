"""
Voice API router.

Provides STT, TTS, and voice-command parsing endpoints.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.voice import parse_voice_command, speech_to_text, text_to_speech

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class TTSRequest(BaseModel):
    text: str
    voice_id: str | None = None


class STTResponse(BaseModel):
    transcript: str


class CommandResponse(BaseModel):
    transcript: str
    action: str
    exercise: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/stt", response_model=STTResponse)
async def stt_endpoint(audio: UploadFile = File(...)) -> STTResponse:
    """
    Accept an uploaded audio file and return the transcribed text.

    Supports WAV, MP3, WebM (browser MediaRecorder default), OGG, M4A.
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file received.")

    logger.info("STT request: filename=%s, size=%d bytes", audio.filename, len(audio_bytes))

    try:
        transcript = await speech_to_text(
            audio_bytes, filename=audio.filename or "audio.wav"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("STT failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"STT service error: {exc}") from exc

    return STTResponse(transcript=transcript)


@router.post("/tts")
async def tts_endpoint(body: TTSRequest) -> Response:
    """
    Accept a text string and return synthesised speech as a WAV audio stream.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text must not be empty.")

    logger.info("TTS request: text_length=%d, voice=%s", len(body.text), body.voice_id)

    try:
        audio_bytes = await text_to_speech(body.text, voice_id=body.voice_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("TTS failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"TTS service error: {exc}") from exc

    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": 'attachment; filename="speech.wav"'},
    )


@router.post("/command", response_model=CommandResponse)
async def voice_command_endpoint(audio: UploadFile = File(...)) -> CommandResponse:
    """
    Accept an audio clip, transcribe it via STT, parse the intent, and return
    a structured action command.

    Example response:
      { "transcript": "start shoulder rehab", "action": "start", "exercise": "shoulder_rotation" }
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file received.")

    logger.info(
        "Voice command request: filename=%s, size=%d bytes", audio.filename, len(audio_bytes)
    )

    try:
        transcript = await speech_to_text(
            audio_bytes, filename=audio.filename or "audio.wav"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("STT for command failed: %s", exc)
        raise HTTPException(
            status_code=502, detail=f"STT service error: {exc}"
        ) from exc

    command = parse_voice_command(transcript)

    return CommandResponse(
        transcript=transcript,
        action=command.get("action", "unknown"),
        exercise=command.get("exercise"),
    )
