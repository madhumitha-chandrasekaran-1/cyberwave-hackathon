"""
Application configuration loaded from environment variables / .env file.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic settings — values are read from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Cyberwave robot arm
    cyberwave_api_key: str = ""
    cyberwave_base_url: str = "https://api.cyberwave.com"

    # Smallest.ai (STT + TTS)
    smallest_api_key: str = ""
    smallest_base_url: str = "https://waves.smallest.ai"

    # OpenAI
    openai_api_key: str = ""

    # Camera
    camera_index: int = 0

    # VLM frame sampling — send every Nth frame to stay within token limits
    vlm_frame_sample_every: int = 5

    # TTS voice ID on smallest.ai
    tts_voice_id: str = "emily"


# Singleton instance imported by all modules
settings = Settings()
