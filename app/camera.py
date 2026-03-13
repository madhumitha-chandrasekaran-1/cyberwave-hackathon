"""
Camera capture module using OpenCV.

Captures frames from a webcam (or rover USB camera) and returns them
as JPEG bytes suitable for passing to the VLM evaluation pipeline.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import TYPE_CHECKING

import cv2

from app.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# In-memory store for the most recent recording session.
# Key: session_id, Value: list of JPEG bytes
_frame_store: dict[str, list[bytes]] = {}


def _open_camera(index: int) -> cv2.VideoCapture | None:
    """Open the camera and return the capture object, or None if unavailable."""
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        logger.warning("Camera index %d could not be opened.", index)
        return None
    return cap


def capture_frames(
    duration_seconds: int = 10,
    fps: int = 5,
    camera_index: int | None = None,
) -> list[bytes]:
    """
    Capture frames from the webcam synchronously.

    This is a blocking call; wrap with asyncio.to_thread() for use inside
    async endpoints.

    Args:
        duration_seconds: How long to record.
        fps: Desired frames per second (actual FPS depends on camera).
        camera_index: Override the configured camera index.

    Returns:
        List of JPEG-encoded frames as bytes. Empty list if camera unavailable.
    """
    index = camera_index if camera_index is not None else settings.camera_index
    cap = _open_camera(index)

    if cap is None:
        logger.error("Camera unavailable — returning empty frame list.")
        return []

    frames: list[bytes] = []
    interval = 1.0 / fps
    start = time.monotonic()

    try:
        logger.info(
            "Recording %ds at ~%d fps from camera index %d", duration_seconds, fps, index
        )
        while time.monotonic() - start < duration_seconds:
            tick = time.monotonic()
            ret, frame = cap.read()
            if not ret:
                logger.warning("Failed to read frame — skipping.")
                continue

            # Encode frame as JPEG
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                frames.append(buf.tobytes())

            # Sleep remainder of interval to approximate target fps
            elapsed = time.monotonic() - tick
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
    finally:
        cap.release()

    logger.info("Captured %d frames (%.1fs)", len(frames), duration_seconds)
    return frames


async def capture_frames_async(
    session_id: str,
    duration_seconds: int = 10,
    fps: int = 5,
) -> list[bytes]:
    """
    Async wrapper around capture_frames() that also caches results by session_id.

    Args:
        session_id: Session identifier used to cache results.
        duration_seconds: Recording window length.
        fps: Target capture rate.

    Returns:
        List of JPEG frame bytes.
    """
    frames = await asyncio.to_thread(capture_frames, duration_seconds, fps)
    _frame_store[session_id] = frames
    return frames


def get_stored_frames(session_id: str) -> list[bytes]:
    """
    Retrieve previously captured frames for a session.

    Args:
        session_id: The session whose frames were cached.

    Returns:
        List of JPEG frame bytes, or empty list if not found.
    """
    return _frame_store.get(session_id, [])


def clear_stored_frames(session_id: str) -> None:
    """Remove cached frames for a session to free memory."""
    _frame_store.pop(session_id, None)


def frame_to_base64(frame_bytes: bytes) -> str:
    """
    Convert JPEG frame bytes to a base64-encoded string.

    This is the format required by the OpenAI vision API (data URIs).

    Args:
        frame_bytes: Raw JPEG bytes from capture_frames().

    Returns:
        Base64-encoded string (without data URI prefix).
    """
    return base64.b64encode(frame_bytes).decode("utf-8")


def frames_to_base64_list(
    frames: list[bytes],
    sample_every: int = 1,
) -> list[str]:
    """
    Convert a list of frame bytes to base64, optionally sub-sampling.

    Args:
        frames: List of JPEG frame bytes.
        sample_every: Keep every Nth frame (1 = keep all, 5 = keep 1-in-5).

    Returns:
        List of base64-encoded strings.
    """
    sampled = frames[::sample_every]
    logger.info(
        "Sampling %d/%d frames (every %dth)", len(sampled), len(frames), sample_every
    )
    return [frame_to_base64(f) for f in sampled]
