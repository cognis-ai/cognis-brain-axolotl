"""Cognis Brain (Axolotl) — brand identity constants. Env-driven."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CognisBrand:
    product_name: str = "Cognis Brain"
    product_tagline: str = "Fine-tunes your private model on your data."
    product_job: str = (
        "Takes your dataset, runs a QLoRA fine-tune on a Cognis GPU, hands the resulting "
        "adapter to vLLM so every Cognis product running for you starts using the new model."
    )
    support_email: str = "support@cognisai.com"
    docs_url: str = "https://cognisai.com/docs/brain"
    portal_url: str = "https://app.cognisai.com/dashboard/brain"


def load_brand() -> CognisBrand:
    return CognisBrand(
        product_name=os.environ.get("COGNIS_PRODUCT_NAME", CognisBrand.product_name),
        product_tagline=os.environ.get("COGNIS_PRODUCT_TAGLINE", CognisBrand.product_tagline),
        product_job=os.environ.get("COGNIS_PRODUCT_JOB", CognisBrand.product_job),
        support_email=os.environ.get("COGNIS_SUPPORT_EMAIL", CognisBrand.support_email),
        docs_url=os.environ.get("COGNIS_DOCS_URL", CognisBrand.docs_url),
        portal_url=os.environ.get("COGNIS_PORTAL_URL", CognisBrand.portal_url),
    )


def branding_enabled() -> bool:
    return os.environ.get("COGNIS_BRANDING", "").strip().lower() in ("on", "true", "1", "yes")
