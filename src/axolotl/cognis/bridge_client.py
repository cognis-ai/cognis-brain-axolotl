"""Cognis Bridge HTTP client (async, aiohttp-based).

The cognis-brain-axolotl fork uses this to talk to Cognis Bridge:

- ``GET /brain-bot/next-job``                  — claim the next queued fine-tune
- ``GET /brain-bot/fine-tunes/{id}``           — fetch full job spec
- ``POST /brain-bot/fine-tunes/{id}/started``  — flip status → running
- ``POST /brain-bot/fine-tunes/{id}/progress`` — periodic metrics
- ``POST /brain-bot/fine-tunes/{id}/completed``— done; hand back adapter S3 path
- ``POST /brain-bot/fine-tunes/{id}/failed``   — crashed; hand back error
- ``POST /brain-bot/events``                   — generic lifecycle events

Auth: ``X-Cognis-Brain-Token: <token>`` header. Token is provisioned by
Bridge at tenant-create time and rotated via the portal. Pod env:
``COGNIS_BRIDGE_URL`` + ``COGNIS_BRAIN_API_TOKEN``.

Uses aiohttp — upstream Axolotl already depends on it via transformers'
streaming utils.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

import aiohttp

logger = logging.getLogger(__name__)


class CognisBridgeError(RuntimeError):
    """Any failure talking to Cognis Bridge."""

    def __init__(self, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class FineTuneJob:
    id: str
    cognis_org_id: str
    name: str
    base_model_id: str
    dataset_s3_path: str
    config: Mapping[str, Any]
    adapter_output_s3_path: str
    bridge_url: str


class BridgeClient:
    """Async client wrapping the Cognis Bridge /brain-bot/* surface."""

    def __init__(
        self,
        bridge_url: str,
        bot_token: str,
        *,
        timeout_s: float = 20.0,
    ) -> None:
        if not bridge_url:
            raise CognisBridgeError("bridge_url is empty")
        if not bot_token or len(bot_token) < 16:
            raise CognisBridgeError("bot_token is empty or too short")
        self._bridge_url = bridge_url.rstrip("/")
        self._bot_token = bot_token
        self._timeout = aiohttp.ClientTimeout(total=timeout_s, connect=5.0)
        self._session: Optional[aiohttp.ClientSession] = None

    @classmethod
    def from_env(cls) -> "BridgeClient":
        bridge_url = os.environ.get("COGNIS_BRIDGE_URL", "").strip()
        bot_token = os.environ.get("COGNIS_BRAIN_API_TOKEN", "").strip()
        if not bridge_url:
            raise CognisBridgeError(
                "COGNIS_BRIDGE_URL is unset. Set it to your Cognis Bridge URL."
            )
        if not bot_token:
            raise CognisBridgeError(
                "COGNIS_BRAIN_API_TOKEN is unset. Get one from the Cognis "
                "portal (Brain → Settings → Rotate bot token)."
            )
        return cls(bridge_url, bot_token)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers={
                    "X-Cognis-Brain-Token": self._bot_token,
                    "Accept": "application/json",
                },
            )
        return self._session

    async def next_job(self) -> Optional[FineTuneJob]:
        session = await self._ensure_session()
        try:
            async with session.get(f"{self._bridge_url}/brain-bot/next-job") as resp:
                body_text = await resp.text()
                if resp.status >= 400:
                    raise CognisBridgeError(
                        f"next_job -> {resp.status}: {body_text[:300]}",
                        status=resp.status,
                    )
                body = _safe_json(body_text)
                job = body.get("job")
                if not job:
                    return None
                return _parse_job(job)
        except aiohttp.ClientError as err:
            raise CognisBridgeError(f"network: {err}") from err

    async def get_job(self, fine_tune_id: str) -> FineTuneJob:
        session = await self._ensure_session()
        try:
            async with session.get(
                f"{self._bridge_url}/brain-bot/fine-tunes/{fine_tune_id}",
            ) as resp:
                body_text = await resp.text()
                if resp.status >= 400:
                    raise CognisBridgeError(
                        f"get_job -> {resp.status}: {body_text[:300]}",
                        status=resp.status,
                    )
                return _parse_job(_safe_json(body_text))
        except aiohttp.ClientError as err:
            raise CognisBridgeError(f"network: {err}") from err

    async def mark_started(
        self,
        fine_tune_id: str,
        *,
        gpu_run_id: str,
        gpu_provider: Optional[str] = None,
    ) -> str:
        body: Dict[str, Any] = {"gpuRunId": gpu_run_id}
        if gpu_provider:
            body["gpuProvider"] = gpu_provider
        resp_body = await self._post(f"/brain-bot/fine-tunes/{fine_tune_id}/started", body)
        return str(resp_body.get("status", ""))

    async def post_progress(
        self,
        fine_tune_id: str,
        *,
        step_latest: int,
        total_steps: int,
        loss_latest: float,
        eta_seconds: Optional[int] = None,
        gpu_hours_used: Optional[float] = None,
    ) -> None:
        body: Dict[str, Any] = {
            "stepLatest": step_latest,
            "totalSteps": total_steps,
            "lossLatest": loss_latest,
        }
        if eta_seconds is not None:
            body["etaSeconds"] = eta_seconds
        if gpu_hours_used is not None:
            body["gpuHoursUsed"] = gpu_hours_used
        await self._post(f"/brain-bot/fine-tunes/{fine_tune_id}/progress", body, expected_status=202)

    async def mark_completed(
        self,
        fine_tune_id: str,
        *,
        adapter_s3_path: str,
        final_metrics: Optional[Dict[str, Any]] = None,
        estimated_cost_usd: Optional[float] = None,
        auto_load: bool = True,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "adapterS3Path": adapter_s3_path,
            "finalMetrics": final_metrics or {},
            "autoLoad": auto_load,
        }
        if estimated_cost_usd is not None:
            body["estimatedCostUsd"] = estimated_cost_usd
        return await self._post(f"/brain-bot/fine-tunes/{fine_tune_id}/completed", body)

    async def mark_failed(
        self,
        fine_tune_id: str,
        *,
        error_message: str,
        estimated_cost_usd: Optional[float] = None,
    ) -> str:
        body: Dict[str, Any] = {"errorMessage": error_message[:8000]}
        if estimated_cost_usd is not None:
            body["estimatedCostUsd"] = estimated_cost_usd
        resp = await self._post(f"/brain-bot/fine-tunes/{fine_tune_id}/failed", body)
        return str(resp.get("status", ""))

    async def post_events(self, events: List[Dict[str, Any]]) -> int:
        if not events:
            return 0
        resp = await self._post("/brain-bot/events", {"events": events}, expected_status=202)
        return int(resp.get("accepted", 0))

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    # -- internals --------------------------------------------------------

    async def _post(
        self,
        path: str,
        body: Dict[str, Any],
        *,
        expected_status: int = 200,
    ) -> Dict[str, Any]:
        session = await self._ensure_session()
        try:
            async with session.post(f"{self._bridge_url}{path}", json=body) as resp:
                body_text = await resp.text()
                if resp.status >= 400:
                    raise CognisBridgeError(
                        f"POST {path} -> {resp.status}: {body_text[:300]}",
                        status=resp.status,
                    )
                if resp.status != expected_status:
                    logger.warning(
                        "Bridge %s returned %d (expected %d)",
                        path,
                        resp.status,
                        expected_status,
                    )
                if not body_text.strip():
                    return {}
                return _safe_json(body_text)
        except aiohttp.ClientError as err:
            raise CognisBridgeError(f"network: {err}") from err


def _safe_json(text: str) -> Dict[str, Any]:
    import json

    try:
        body = json.loads(text)
    except json.JSONDecodeError as err:
        raise CognisBridgeError(f"Bridge returned non-JSON: {text[:200]}") from err
    if not isinstance(body, dict):
        raise CognisBridgeError("Bridge returned a non-object JSON body")
    return body


def _parse_job(raw: Mapping[str, Any]) -> FineTuneJob:
    return FineTuneJob(
        id=str(raw.get("id", "")),
        cognis_org_id=str(raw.get("cognisOrgId", "")),
        name=str(raw.get("name", "")),
        base_model_id=str(raw.get("baseModelId", "")),
        dataset_s3_path=str(raw.get("datasetS3Path", "")),
        config=raw.get("config") or {},
        adapter_output_s3_path=str(raw.get("adapterOutputS3Path", "")),
        bridge_url=str(raw.get("bridgeUrl", "")),
    )
