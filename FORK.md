# Fork of axolotl-ai-cloud/axolotl

This repo is a **soft fork** of [`axolotl-ai-cloud/axolotl`](https://github.com/axolotl-ai-cloud/axolotl), maintained as `cognis-brain-axolotl` under the Cognis AI platform. License posture: Apache-2.0 core only. Upstream is single-tier Apache-2.0 — no `enterprise/`, `ee/`, `cloud/`, `pro/`, `premium/`, `commercial/`, or `saas/` proprietary-tier directories exist, so no strip recipe is required at fork time.

Cognis Brain Axolotl is the **fine-tuning / LoRA training** half of Cognis Brain (Phase 6, the private-LLM offering). Per-tenant brain-plan customers get a fine-tuned model produced by this trainer; the resulting weights are then served by `cognis-brain-vllm`. This repo is **not a runtime LLM consumer** — it IS the training tool — so the platform's "wrap LLM via `@cognis/llm-client`" rule doesn't apply to source here. What does apply: config recipes, dataset-loader plugins, and any Bridge integration glue must be Cognis-flavored.

## Brain-stack siblings

| Cognis repo | Upstream | Role |
| --- | --- | --- |
| `cognis-brain-axolotl` (this repo) | axolotl-ai-cloud/axolotl | LoRA / SFT / DPO fine-tuning pipeline |
| `cognis-brain-vllm` | vllm-project/vllm | Private model serving (loads weights produced here) |
| `cognis-brain-ragflow` | infiniflow/ragflow | RAG / retrieval layer |

All three were forked early to preserve their Apache-2.0 license windows ahead of any future relicense by upstream. The integration product (`cognis-ai/cognis-brain` — not a fork, a thin glue layer) gets stood up in Phase 6.

## Branches

| Branch | Purpose |
| --- | --- |
| `vendor/upstream` | Mirror of `axolotl-ai-cloud/axolotl:main`. NEVER edit. Rebased by the nightly bot. |
| `cognis/main` | Cognis work. Rebased monthly onto `vendor/upstream`. Default branch. |

## Commit prefixes (grep-friendly across rebases)

- `fork:` — surgical edits to upstream files (last resort; prefer config/plugin layering)
- `brand:` — branding (logo assets, default-recipe naming)
- `wire:` — Cognis integration plumbing (Bridge job-submission webhook, S3 weight upload, training-run telemetry to Langfuse)
- `ci:` — GitHub Actions, license gate, rebase bot
- `docs:` — FORK.md, CLAUDE.md, CODEOWNERS, READMEs

## License-trap status

Verified 2026-05-12 at upstream SHA `b7ec06b8a17966e2de405783db677fe6cc68835f`:

- LICENSE is plain Apache-2.0 (no Commons Clause rider, no addendum)
- No `enterprise/`, `ee/`, `pro/`, `premium/`, `commercial/`, `saas/`, `platform/` trap directories at any depth
- `examples/cloud/` (Modal/Baseten YAMLs) and `src/axolotl/cli/cloud/` (Modal/Baseten launcher CLI) are **functional cloud-runner adapters**, NOT proprietary-tier directories — Apache-2.0 source for users who want to launch jobs on third-party GPU clouds. Allowed.
- `pyproject.toml` declares `axolotl` with optional-deps grouped by purpose only — no premium extra
- Two transitive deps to watch: `axolotl-contribs-lgpl==0.0.7` (LGPL — runtime-linked, not in our source) and `axolotl-contribs-mit==0.0.6`. LGPL is acceptable as a runtime dep but NOT acceptable to vendor or re-license source from. The license-gate scans source only, so transitive deps don't trip it — but a re-vendoring of contribs-lgpl into this repo's `src/` WOULD trip it.

If upstream adds a `pro/` / `ee/` / equivalent directory in a future rebase, the strip happens in a **separate commit** before merging — same doctrine as `cognis-support`.

## Fork-diff target

≤3% of upstream LOC (default per fork-ops.md). Tracked on every PR via `git diff vendor/upstream...cognis/main --stat`. Hard cap 5% — build fails above that. Axolotl is dense Python (training pipelines, config schemas) and we have very little reason to surgically edit it — almost all Cognis-specific behavior should land as new Bridge-facing modules or YAML recipes.

## Rebase cadence

- Nightly bot: `.github/workflows/upstream-rebase.yml` (workflow present; **cron commented at fork-bootstrap** — flip on only after the first manual `workflow_dispatch` produces a clean rebase or a tractable conflict against Axolotl's release pace, which is fast-moving)
- Auto-merge clean rebases via Mergify (configured at platform level once first rebase lands)
- Conflicts → bot opens issue labeled `rebase-conflict`; human review
- Shared `rerere-cache` committed to `cognis-platform/infra/rerere-cache/cognis-brain-axolotl/`

## Cognis-side surface

What lives on `cognis/main` (and ONLY here):

- `FORK.md`, `CLAUDE.md`, `CODEOWNERS` — fork meta
- `.github/workflows/license-gate.yml` — ScanCode allowlist enforcement
- `.github/workflows/upstream-rebase.yml` — nightly rebase bot (cron commented)
- `tools/check_no_proprietary.py` — license allowlist enforcement
- (future Phase 6) `examples/cognis/` — Cognis-flavored training recipes (per-tenant LoRA on top of a base model, output to S3 path consumed by `cognis-brain-vllm`)
- (future Phase 6) `src/axolotl/integrations/cognis_bridge/` — optional plugin that posts training-run lifecycle events (queued / running / done / failed) to Bridge so the platform UI can show training progress and bill GPU-hours
- (future Phase 6) `src/axolotl/integrations/cognis_telemetry/` — wandb-or-Langfuse adapter pinning runs at `langfuse.cognisai.com`

All product-level multi-tenant logic (org → training-job mapping, GPU-budget meters, weight-artifact ACLs) lives in `cognis-platform/apps/bridge`, NOT here. This repo IS the trainer.

## Runtime constraints (apply to Cognis-flavored modules)

- This repo runs on GPU pods, NOT in the Bridge process. Bridge submits a job (REST call to a job-queue), a GPU pod picks it up, runs `axolotl train <recipe>.yaml`, and posts back. Don't import Bridge code; talk to Bridge over HTTP.
- LLM API calls (e.g. judge-model evals during training) should still go through `llm.cognisai.com` — the same LiteLLM proxy URL the rest of the platform uses. Use the OpenAI-compatible client pointed at that base URL; no special wrapper required because Axolotl already has OpenAI-compatible eval hooks.
- Per-tenant model output paths MUST be Bridge-issued, e.g. `s3://cognis-brain-weights/<org_id>/<run_id>/`. Never hard-code paths.

## Upstream-PR policy

Contribute back to `axolotl-ai-cloud/axolotl` *before* merging to `cognis/main`:

- Bug fixes, perf patches, test improvements, type fixes, refactors that shrink fork diff
- New trainer features that are generic (not Cognis-specific)

Keep in fork (do NOT upstream):

- Bridge integration plugin (Cognis-specific webhooks)
- Cognis telemetry adapter, branding, billing meters, per-tenant weight ACLs
- Anything pinning a Cognis service hostname

## References

- Fork-ops doctrine: `cognis-platform/docs/specs/fork-ops.md`
- Bridge integration spec: `cognis-platform/docs/specs/bridge-service.md`
- LLM gateway: `cognis-platform/docs/specs/ai-gateway.md`
