# Cognis Brain — Axolotl fine-tune pod

Fine-tunes private models for Cognis tenants on demand. A pod boots, claims the next queued fine-tune from Cognis Bridge, runs the training, uploads the adapter to S3, and tells Bridge to load it into vLLM.

## What this repo is

A soft fork of `axolotl-ai-cloud/axolotl` (Apache-2.0). Cognis-specific code lives under `src/axolotl/cognis/` — everything else is upstream Axolotl, untouched.

| File | Role |
|------|------|
| `src/axolotl/cognis/bridge_client.py` | Async aiohttp client to Cognis Bridge `/brain-bot/*` |
| `src/axolotl/cognis/cli.py`           | Pod entrypoint. Bridge-mode → claim job + train + upload. No env → upstream CLI parity |
| `src/axolotl/cognis/branding/`        | Brand strings + CLI banner |
| `Dockerfile.cognis`                   | Pod image with telemetry-off defaults + entrypoint |

## How a fine-tune runs

```
1. Customer submits fine-tune in Cognis portal → Bridge `/v1/brain/fine-tunes`
2. Job lands in `brain_fine_tune_jobs` (status=queued)
3. Operator (or Modal/Runpod autoscaler) spawns a cognis-brain-axolotl pod with:
     COGNIS_BRIDGE_URL=https://bridge.cognisai.com
     COGNIS_BRAIN_API_TOKEN=<bot token from portal>
4. Pod boots → `python -m axolotl.cognis.cli`
5. Pod claims the next queued job → POST /brain-bot/fine-tunes/{id}/started
6. Pod writes Axolotl YAML to /tmp + runs `axolotl train ...`
7. On clean exit: pod uploads adapter to s3://cognis-brain-adapters/<org>/<job>/adapter_model.safetensors
                  + POST /brain-bot/fine-tunes/{id}/completed
8. Bridge calls vLLM `POST /v1/load_lora_adapter` with the new adapter path
9. The tenant's `cognis-smart` calls now serve from their newly-trained model
```

## Quick start

### Production (Modal or Runpod GPU pod)

```bash
docker build -t ghcr.io/cognis-ai/brain-axolotl:latest -f Dockerfile.cognis .
docker push ghcr.io/cognis-ai/brain-axolotl:latest
```

Then have Bridge spawn it on the GPU provider of choice. Modal example:

```python
import modal
app = modal.App("cognis-brain-axolotl")
@app.function(gpu="A100", image=modal.Image.from_registry("ghcr.io/cognis-ai/brain-axolotl:latest"),
              secrets=[modal.Secret.from_name("cognis-bridge")])
def fine_tune():
    import subprocess
    subprocess.run(["python", "-m", "axolotl.cognis.cli"], check=True)
```

### Local dev (stub mode)

Without `COGNIS_BRIDGE_URL` set, the wrapper falls through to upstream's `axolotl` CLI for parity testing:

```bash
python -m axolotl.cognis.cli train examples/llama-3/qlora.yml
```

## License + support

Apache-2.0 throughout. Portal: <https://app.cognisai.com/dashboard/brain>. Support: <support@cognisai.com>.
