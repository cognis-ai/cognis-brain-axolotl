"""Cognis Brain (Axolotl) — CLI banner."""

from __future__ import annotations

import sys
import textwrap
from typing import TextIO

from axolotl.cognis.branding.cognis_brand import branding_enabled, load_brand

_BANNER_WIDTH = 78


def print_cognis_banner(stream: TextIO = sys.stdout) -> None:
    if not branding_enabled():
        return
    brand = load_brand()
    bar = "=" * _BANNER_WIDTH
    paragraphs = [
        bar,
        "",
        brand.product_name.center(_BANNER_WIDTH),
        brand.product_tagline.center(_BANNER_WIDTH),
        "",
        bar,
        "",
        "What this is",
        "-" * len("What this is"),
        textwrap.fill(brand.product_job, width=_BANNER_WIDTH),
        "",
        "Where to go for help",
        "-" * len("Where to go for help"),
        f"  Portal:  {brand.portal_url}",
        f"  Docs:    {brand.docs_url}",
        f"  Support: {brand.support_email}",
        "",
        bar,
        "",
    ]
    stream.write("\n".join(paragraphs))
    stream.flush()


def cognis_log_prefix() -> str:
    return "Cognis Brain"
