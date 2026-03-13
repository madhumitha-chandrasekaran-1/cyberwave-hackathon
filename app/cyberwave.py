"""
Cyberwave API client for SO101 robot arm control.

The Cyberwave REST API uses Bearer token authentication.
Endpoint pattern:  POST /api/v1/workflows/{workflow_id}/run
                   GET  /api/v1/workflows/{workflow_id}/status
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exercise → Cyberwave workflow ID mapping
# Replace placeholder UUIDs with real workflow IDs from your Cyberwave project
# ---------------------------------------------------------------------------
EXERCISE_WORKFLOWS: dict[str, str] = {
    "shoulder_rotation": "wf-00000000-0001-0001-0001-000000000001",
    "elbow_flex":        "wf-00000000-0001-0001-0001-000000000002",
    "wrist_rotation":    "wf-00000000-0001-0001-0001-000000000003",
}


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.cyberwave_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


class CyberwaveClient:
    """Async HTTP client wrapping the Cyberwave workflow API."""

    def __init__(self) -> None:
        self._base = settings.cyberwave_base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Core API methods
    # ------------------------------------------------------------------

    async def trigger_workflow(
        self,
        workflow_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Trigger a named Cyberwave workflow.

        Args:
            workflow_id: The workflow UUID registered in Cyberwave.
            payload: Optional JSON body forwarded to the workflow.

        Returns:
            Cyberwave API response as a dict (includes run_id, status, etc.).

        Raises:
            httpx.HTTPStatusError: On non-2xx response.
        """
        url = f"{self._base}/api/v1/workflows/{workflow_id}/run"
        logger.info("Triggering Cyberwave workflow %s", workflow_id)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=_headers(), json=payload or {})
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            logger.info("Workflow %s triggered → run_id=%s", workflow_id, data.get("run_id"))
            return data

    async def get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        """
        Poll the status of a workflow run.

        Args:
            workflow_id: The workflow UUID.

        Returns:
            Dict containing at minimum {"status": "running"|"completed"|"failed"}.
        """
        url = f"{self._base}/api/v1/workflows/{workflow_id}/status"
        logger.debug("Polling workflow status for %s", workflow_id)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            return resp.json()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # High-level helper
    # ------------------------------------------------------------------

    async def demonstrate_exercise(self, exercise_name: str) -> dict[str, Any]:
        """
        Look up the Cyberwave workflow for *exercise_name* and trigger it so
        the SO101 arm performs the demonstration motion.

        Args:
            exercise_name: One of the keys in EXERCISE_WORKFLOWS
                           ("shoulder_rotation", "elbow_flex", "wrist_rotation").

        Returns:
            Cyberwave trigger response dict.

        Raises:
            ValueError: If the exercise is not mapped to a workflow.
            httpx.HTTPStatusError: On API error.
        """
        workflow_id = EXERCISE_WORKFLOWS.get(exercise_name)
        if workflow_id is None:
            available = ", ".join(EXERCISE_WORKFLOWS.keys())
            raise ValueError(
                f"Unknown exercise '{exercise_name}'. Available: {available}"
            )

        logger.info("Demonstrating exercise '%s' via workflow %s", exercise_name, workflow_id)
        return await self.trigger_workflow(
            workflow_id,
            payload={"exercise": exercise_name, "source": "physiobot"},
        )


# Module-level singleton — import and use directly
cyberwave_client = CyberwaveClient()
