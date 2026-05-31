"""Cognis Brain — productization surface for the cognis-brain-axolotl fork.

This package is the *only* Cognis-specific code in the fork. Everything else
under ``src/axolotl/`` is upstream Axolotl, untouched. Contract:

- ``bridge_client.BridgeClient`` — async aiohttp client to Cognis Bridge's
  ``/brain-bot/*`` surface (claim next job, post lifecycle events, post
  fine-tune completion with adapter S3 path).
- ``cli.main`` — wrapper entrypoint. If Cognis env is set, pulls the next
  queued job from Bridge, writes the Axolotl YAML to a temp file, runs
  ``axolotl.cli.train``, posts back progress + completion. Otherwise
  defers to upstream's CLI for parity-mode local testing.
- ``branding.cognis_brand`` / ``branding.banner`` — env-driven brand
  strings + ASCII banner that replaces upstream's print_axolotl_text_art
  when COGNIS_BRANDING=on.

NEVER import ``openai`` / ``anthropic`` / ``litellm`` directly — Axolotl
trains models, it doesn't call LLM APIs at inference time.
"""

__all__ = ["bridge_client", "cli", "branding"]
