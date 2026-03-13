"""
Smallest.ai integration for speech-to-text (STT) and text-to-speech (TTS).

Smallest.ai REST API:
  TTS  →  POST https://waves.smallest.ai/api/v1/lightning/get_speech
  STT  →  POST https://waves.smallest.ai/api/v1/asr          (multipart audio)

Docs: https://waves.smallest.ai/docs
"""

from __future__ import annotations

import io
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoint paths (relative to SMALLEST_BASE_URL)
# ---------------------------------------------------------------------------
TTS_PATH = "/api/v1/lightning/get_speech"
STT_PATH = "/api/v1/asr"


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.smallest_api_key}",
    }


async def text_to_speech(text: str, voice_id: str | None = None) -> bytes:
    """
    Convert text to speech using the smallest.ai Lightning TTS API.

    Args:
        text: The spoken text to synthesise.
        voice_id: Voice identifier. Defaults to the configured TTS voice.

    Returns:
        Raw audio bytes (WAV or MP3 depending on smallest.ai response).

    Raises:
        httpx.HTTPStatusError: On non-2xx API response.
        ValueError: If the API returns an empty body.
    """
    voice = voice_id or settings.tts_voice_id
    url = f"{settings.smallest_base_url.rstrip('/')}{TTS_PATH}"

    payload = {
        "text": text,
        "voice_id": voice,
        "sample_rate": 24000,
        "speed": 1.0,
        "add_wav_header": True,
    }

    logger.info("TTS request: voice=%s, text_length=%d", voice, len(text))

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()

    audio_bytes = resp.content
    if not audio_bytes:
        raise ValueError("smallest.ai TTS returned empty audio body.")

    logger.info("TTS response: %d bytes received", len(audio_bytes))
    return audio_bytes


async def speech_to_text(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """
    Transcribe speech audio using the smallest.ai ASR (STT) API.

    Args:
        audio_bytes: Raw audio file bytes (WAV, MP3, WebM, OGG, etc.).
        filename: Filename hint used when constructing the multipart upload.

    Returns:
        Transcribed text string (may be empty if speech is inaudible).

    Raises:
        httpx.HTTPStatusError: On non-2xx API response.
    """
    url = f"{settings.smallest_base_url.rstrip('/')}{STT_PATH}"

    logger.info("STT request: audio_size=%d bytes, filename=%s", len(audio_bytes), filename)

    # Determine MIME type from filename extension
    ext = filename.rsplit(".", 1)[-1].lower()
    mime_map = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "webm": "audio/webm",
        "ogg": "audio/ogg",
        "m4a": "audio/mp4",
    }
    mime_type = mime_map.get(ext, "audio/wav")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            url,
            headers=_auth_headers(),
            files={"file": (filename, io.BytesIO(audio_bytes), mime_type)},
        )
        resp.raise_for_status()

    data = resp.json()
    # smallest.ai returns {"text": "...", ...}
    transcript: str = data.get("text", "").strip()
    logger.info("STT result: '%s'", transcript)
    return transcript


def parse_voice_command(transcript: str) -> dict[str, str]:
    """
    Parse a voice transcript into a structured command dict.

    Understands intents:
      - start  → { "action": "start", "exercise": "<name>" }
      - stop   → { "action": "stop" }
      - repeat → { "action": "repeat" }
      - question/status → { "action": "status" }

    Args:
        transcript: Raw STT transcript string.

    Returns:
        Dict with at least an "action" key.
    """
    text = transcript.lower().strip()

    # Map spoken exercise names to internal keys
    exercise_map = {
        "shoulder": "shoulder_rotation",
        "shoulder rotation": "shoulder_rotation",
        "shoulder rehab": "shoulder_rotation",
        "elbow": "elbow_flex",
        "elbow flex": "elbow_flex",
        "elbow flexion": "elbow_flex",
        "wrist": "wrist_rotation",
        "wrist rotation": "wrist_rotation",
    }

    if any(word in text for word in ("start", "begin", "let's go", "lets go")):
        exercise = "shoulder_rotation"  # default
        for phrase, key in exercise_map.items():
            if phrase in text:
                exercise = key
                break
        return {"action": "start", "exercise": exercise}

    if any(word in text for word in ("stop", "end", "finish", "done", "quit")):
        return {"action": "stop"}

    if any(word in text for word in ("again", "repeat", "redo", "once more")):
        return {"action": "repeat"}

    if any(word in text for word in ("how", "status", "score", "did i", "result")):
        return {"action": "status"}

    # Fallback — unrecognised command
    return {"action": "unknown", "transcript": transcript}
