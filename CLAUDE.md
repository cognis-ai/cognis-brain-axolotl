# Cognis Brain Axolotl — repo context for Claude

This is a soft fork of `axolotl-ai-cloud/axolotl`. **The fork is not the product — `cognis-platform/apps/bridge` is.** Every hour spent editing Axolotl's trainer internals here costs 3× at next rebase. This repo IS the training tool: it runs on GPU pods, fine-tunes models, and writes weights to per-tenant S3 paths. Bridge orchestrates jobs over HTTP; we do not import Bridge code.

## Branches

- `cognis/main` — default. Cognis work.
- `vendor/upstream` — mirror of axolotl-ai-cloud/axolotl:main. NEVER edit.

## Hard rules

1. **No license traps to restore.** Upstream is Apache-2.0 single-tier (verified at fork time, SHA `b7ec06b8a17966e2de405783db677fe6cc68835f`, 2026-05-12). `examples/cloud/` and `src/axolotl/cli/cloud/` are functional Modal/Baseten adapters, NOT proprietary-tier dirs — keep them. If upstream introduces `pro/`, `ee/`, `enterprise/`, `premium/`, `commercial/`, or `saas/` directories in a future rebase, strip in a SEPARATE commit before merging — never restore them.
2. **Never edit upstream Python casually.** Axolotl exposes extension points that survive rebases:
   - `src/axolotl/integrations/` — drop a new package here; the trainer auto-registers it. This is the right place for Cognis Bridge webhooks and telemetry adapters.
   - `examples/` — Cognis-flavored YAML training recipes go in a new `examples/cognis/` subdir; they don't touch upstream code.
   - `src/axolotl/cli/cloud/` is a plugin surface for cloud launchers (Modal, Baseten). If we ever ship a Cognis-managed launcher, it goes alongside as a new sibling — never replacing existing ones.
   If you must touch an upstream file, the PR upstream is **mandatory** before merging to `cognis/main`.
3. **Fork-diff cap: 5% of upstream LOC.** Tracked per-PR. Target ≤3%.
4. **Commit prefixes only:** `fork:` / `brand:` / `wire:` / `ci:` / `docs:`.
5. **All Cognis-specific multi-tenant + billing logic goes in Bridge.** This repo holds: training recipes, Cognis-branded defaults, an optional Bridge-webhook integration, an optional telemetry adapter, FORK.md/CLAUDE.md/CODEOWNERS.
6. **Never vendor a non-allowlisted dep into `src/`.** Transitive `axolotl-contribs-lgpl` is fine as a pip-installed runtime dependency; copying its source into this repo would be a license-gate failure.
7. **The "@cognis/llm-client wrap" rule does NOT apply to source here** — Axolotl IS the training tool, not an LLM consumer. EXCEPTION: if we add judge-model evals or RLHF reward calls, the OpenAI-compatible base URL MUST be `https://llm.cognisai.com` (the platform LiteLLM proxy), never a raw provider.

## Stack (upstream)

- Python ≥3.10
- PyTorch ≥2.9 + CUDA (training is GPU-only; CPU is for dev / dataset prep only)
- Transformers / Accelerate / PEFT / TRL / Datasets / DeepSpeed
- Hydra-style YAML configs (`examples/*.yml`) — the user-facing API
- `setuptools_scm` + `pyproject.toml` (no Poetry, no `uv` here — upstream stays on pip)
- Pytest for tests; `pytest tests/`
- Modal + Baseten as supported cloud launchers (cli/cloud/)
- HuggingFace Hub for model + dataset loading
- W&B + Trackio + (planned) Langfuse for run telemetry

## Build & test (upstream Axolotl tooling)

This is upstream Axolotl tooling — do NOT run install/build commands as part of fork-bootstrap. When Phase 6 builds out:

- `pip install -e .` — editable install with dev deps (run on a CUDA box)
- `pytest tests/` — unit + integration suite
- `axolotl train examples/cognis/<recipe>.yml` — run a training job
- `docker build -f docker/Dockerfile .` — base trainer image
- `docker compose up` — dev compose (mostly for HF cache + logs; the GPU is on the host)

Stay on upstream's tooling (pip + setuptools_scm). Don't introduce Poetry, uv, or hatch into this repo.

## What lives here

Currently (post-bootstrap):
- `FORK.md`, `CLAUDE.md`, `CODEOWNERS` — fork meta
- `.github/workflows/license-gate.yml` — ScanCode + trap-dir gate
- `.github/workflows/upstream-rebase.yml` — nightly rebase bot (cron **commented** at bootstrap)
- `tools/check_no_proprietary.py` — license allowlist enforcement

Planned (Phase 6):
- `src/axolotl/integrations/cognis_bridge/` — training-run lifecycle webhooks to Bridge (queued / running / step-progress / done / failed), per-tenant S3 weight-output path resolution
- `src/axolotl/integrations/cognis_telemetry/` — Langfuse adapter pinning runs at `langfuse.cognisai.com`, GPU-hour billing emit
- `examples/cognis/` — Cognis-flavored recipes (per-tenant LoRA on small base + larger base, DPO templates, default eval suite)
- `docker/cognis.Dockerfile` — minimal trainer image with the integrations pre-baked, pulled by the Bridge job-runner

## Auth pattern with Bridge

This repo doesn't have a HTTP server of its own — it's a CLI. Bridge submits jobs to a queue (BullMQ or k8s Job); a GPU pod pulls a job and runs `axolotl train`. Auth between the pod and Bridge:

- Pod calls Bridge with a short-lived JWT issued at job-dispatch time
- Bridge resolves `org_id` from the JWT; the pod gets pre-signed S3 URLs back for input dataset + output weights
- Pod posts lifecycle events to a Bridge webhook with the same JWT

The integration plugin (`src/axolotl/integrations/cognis_bridge/`) handles this. No JWT logic in upstream files.

## Cost policy

This fork inherits Cognis's managed-SaaS cost policy — see `../cognis-platform/docs/specs/cost-policy.md` for the full per-fork list and rationale. For `cognis-brain-axolotl` specifically, in production deploys DO NOT set: `WANDB_API_KEY` (set `WANDB_DISABLED=true` or point at a self-host instead), `POSTHOG_API_KEY`. Axolotl defaults to W&B Cloud; disable unless a customer explicitly pays for it.

## What NOT to do

- Don't restore stripped trap directories (currently there are none — keep it that way)
- Don't add NestJS / Bridge logic here — that's in `cognis-platform/apps/bridge`
- Don't touch `vendor/upstream` directly — it's a mirror branch
- Don't commit credentials; HuggingFace tokens, W&B keys, S3 keys go in env / pod secrets
- Don't `pip install` premium plugins from upstream's ecosystem if any appear later — license-gate must approve them first
- Don't replace `pip` / `setuptools_scm` with Poetry or uv — upstream chose pip, rebases stay easy if we do too
- Don't flip the rebase cron in this bootstrap commit — it stays commented until first manual run is verified
- Don't hard-code model output paths — Bridge issues them per-job
- Don't import `openai` or `anthropic` directly in Cognis-flavored modules. If judge-model evals need API access, point at `https://llm.cognisai.com` (OpenAI-compatible) and let LiteLLM route
