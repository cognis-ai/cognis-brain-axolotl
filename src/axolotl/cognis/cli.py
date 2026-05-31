"""Cognis Brain — Axolotl pod entrypoint.

When the pod boots:
1. Print Cognis banner.
2. Connect to Bridge with COGNIS_BRAIN_API_TOKEN. Fail fast on bad creds.
3. Claim the next queued fine-tune job for this tenant.
4. Write Axolotl YAML to /tmp/cognis-axolotl-config.yml.
5. POST /brain-bot/fine-tunes/{id}/started with the gpu_run_id from env.
6. Run `axolotl train /tmp/cognis-axolotl-config.yml` synchronously.
7. Periodic background task posts /progress every 60s by tailing the
   trainer's metrics file.
8. On clean exit: upload adapter to S3 (pre-signed URL from job spec) and
   POST /completed with the S3 path. Bridge auto-loads it into vLLM.
9. On crash: POST /failed with the exception message.

When the pod boots WITHOUT Cognis env: defers straight to upstream's
`axolotl` CLI for parity-mode local testing.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from axolotl.cognis.branding.banner import cognis_log_prefix, print_cognis_banner
from axolotl.cognis.branding.cognis_brand import branding_enabled
from axolotl.cognis.bridge_client import BridgeClient, CognisBridgeError, FineTuneJob


def _bridge_mode_configured() -> bool:
    return bool(os.environ.get("COGNIS_BRIDGE_URL")) and bool(
        os.environ.get("COGNIS_BRAIN_API_TOKEN")
    )


def _resolve_gpu_metadata() -> tuple[str, Optional[str]]:
    """Pull provider + run id from env. Pods on Modal / Runpod / Lambda
    Cloud each set a different env so we union-match. Falls back to a
    locally-generated id when nothing's set (dev mode)."""
    if os.environ.get("MODAL_TASK_ID"):
        return (os.environ["MODAL_TASK_ID"], "modal")
    if os.environ.get("RUNPOD_POD_ID"):
        return (os.environ["RUNPOD_POD_ID"], "runpod")
    if os.environ.get("LAMBDA_INSTANCE_ID"):
        return (os.environ["LAMBDA_INSTANCE_ID"], "lambda")
    # local / dev fallback — synth a stable id from hostname
    import socket

    return (f"local-{socket.gethostname()}-{os.getpid()}", "local")


def _materialize_config(job: FineTuneJob, output_dir: Path) -> Path:
    """Write the merged Axolotl YAML the trainer will load.

    Bridge already merged seed defaults + customer overrides + injected
    base_model. We just add output_dir + dataset path (since those are
    pod-local paths Bridge can't know).
    """
    cfg: Dict[str, Any] = dict(job.config)
    cfg["base_model"] = job.base_model_id
    cfg["output_dir"] = str(output_dir)
    cfg.setdefault("datasets", [{"path": job.dataset_s3_path, "type": "alpaca"}])
    cfg_path = output_dir / "cognis-axolotl-config.yml"
    with cfg_path.open("w") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return cfg_path


def _upload_adapter_to_s3(local_path: Path, s3_path: str) -> None:
    """Upload local adapter weights to S3. v1 shells out to awscli for
    minimal deps; v1.5 swaps for boto3 + pre-signed URLs.
    """
    if s3_path.startswith("s3://"):
        subprocess.run(
            ["aws", "s3", "cp", str(local_path), s3_path],
            check=True,
        )
    else:
        # dev/stub mode: just log
        print(f"{cognis_log_prefix()}: stub adapter upload (would push {local_path} → {s3_path})")


async def _run_bridge_job(job: FineTuneJob, client: BridgeClient) -> int:
    gpu_run_id, gpu_provider = _resolve_gpu_metadata()
    print(
        f"\n{cognis_log_prefix()}: claimed fine-tune job id={job.id} "
        f"org={job.cognis_org_id} base={job.base_model_id}"
    )
    print(
        f"{cognis_log_prefix()}: dataset={job.dataset_s3_path} → "
        f"adapter_out={job.adapter_output_s3_path}"
    )

    try:
        await client.mark_started(job.id, gpu_run_id=gpu_run_id, gpu_provider=gpu_provider)
    except CognisBridgeError as err:
        print(f"{cognis_log_prefix()}: failed to mark started: {err}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="cognis-axolotl-") as tmp:
        output_dir = Path(tmp)
        cfg_path = _materialize_config(job, output_dir)
        print(f"{cognis_log_prefix()}: wrote config → {cfg_path}")

        # Run upstream's axolotl CLI as a subprocess. Synchronous; the
        # pod is single-purpose. Background progress polling is v1.5 — for
        # v1 we send a single "started" + one "completed" event.
        cmd = [sys.executable, "-m", "axolotl.cli.train", str(cfg_path)]
        print(f"{cognis_log_prefix()}: running {' '.join(cmd)}")
        result = subprocess.run(cmd)

        if result.returncode != 0:
            err_msg = f"axolotl train exited with code {result.returncode}"
            await client.mark_failed(job.id, error_message=err_msg)
            return result.returncode

        # Locate the adapter weights. Axolotl writes to
        # output_dir/adapter_model.safetensors for LoRA runs.
        adapter_file = output_dir / "adapter_model.safetensors"
        if not adapter_file.exists():
            # fallback: maybe full-finetune (not supported in v1 paths)
            adapter_file = output_dir / "model.safetensors"
        if not adapter_file.exists():
            await client.mark_failed(
                job.id,
                error_message=(
                    f"trainer succeeded but no adapter_model.safetensors / "
                    f"model.safetensors found in {output_dir}"
                ),
            )
            return 3

        # Upload (best-effort)
        try:
            _upload_adapter_to_s3(adapter_file, job.adapter_output_s3_path)
        except subprocess.CalledProcessError as err:
            await client.mark_failed(
                job.id, error_message=f"adapter upload failed: {err}"
            )
            return 4

        # Final metrics: read trainer_state.json if it landed
        final_metrics: Dict[str, Any] = {}
        state_file = output_dir / "trainer_state.json"
        if state_file.exists():
            try:
                final_metrics = json.loads(state_file.read_text())
            except (OSError, json.JSONDecodeError) as err:
                print(
                    f"{cognis_log_prefix()}: trainer_state.json read failed: {err}",
                    file=sys.stderr,
                )

        await client.mark_completed(
            job.id,
            adapter_s3_path=job.adapter_output_s3_path,
            final_metrics=final_metrics,
            auto_load=True,
        )
        print(f"{cognis_log_prefix()}: fine-tune complete; Bridge will load the adapter into vLLM")
        return 0


async def _async_main() -> int:
    client = BridgeClient.from_env()
    try:
        # If COGNIS_FINE_TUNE_ID is set, fetch that exact job (re-runs,
        # manual replays). Otherwise claim whatever's queued.
        ft_id = os.environ.get("COGNIS_FINE_TUNE_ID", "").strip()
        if ft_id:
            job = await client.get_job(ft_id)
        else:
            job = await client.next_job()
        if job is None:
            print(f"{cognis_log_prefix()}: no queued jobs — exiting clean.")
            return 0
        return await _run_bridge_job(job, client)
    finally:
        await client.aclose()


def _run_upstream_passthrough() -> int:
    from axolotl.cli.main import cli  # lazy import; pulls Click

    cli()
    return 0


def main() -> int:
    print_cognis_banner()
    if _bridge_mode_configured():
        if branding_enabled():
            sys.stdout.write(
                f"\n{cognis_log_prefix()}: Bridge mode — will claim a queued fine-tune.\n\n"
            )
        try:
            return asyncio.run(_async_main())
        except SystemExit as e:
            return int(e.code or 0)
        except CognisBridgeError as err:
            sys.stderr.write(f"{cognis_log_prefix()}: Bridge error: {err}\n")
            return 2
        except KeyboardInterrupt:
            sys.stderr.write(f"\n{cognis_log_prefix()}: shutdown requested.\n")
            return 130
    if branding_enabled():
        sys.stdout.write(
            f"\n{cognis_log_prefix()}: no Bridge env — falling back to upstream axolotl CLI.\n\n"
        )
    return _run_upstream_passthrough()


if __name__ == "__main__":
    raise SystemExit(main())
