"""
scripts/train_variants.py

Trains all three model variants in sequence:
  baseline  → models/nrfi_model.pkl
  var_a     → models/nrfi_model_var_a.pkl   (First-Inning Specialist)
  var_b     → models/nrfi_model_var_b.pkl   (Team Trends)

Usage:
    python scripts/train_variants.py
    python scripts/train_variants.py --variants baseline var_a   # subset
"""

from __future__ import annotations

import argparse
import logging
import sys

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from backend.modeling.train_model import VARIANT_WEIGHTS, train


def main() -> None:
    parser = argparse.ArgumentParser(description="Train all NRFI model variants.")
    parser.add_argument(
        "--variants",
        nargs="+",
        default=list(VARIANT_WEIGHTS.keys()),
        choices=list(VARIANT_WEIGHTS.keys()),
        help="Which variants to train (default: all)",
    )
    args = parser.parse_args()

    for variant in args.variants:
        logger.info("=" * 60)
        logger.info("Training variant: %s", variant)
        logger.info("=" * 60)
        try:
            train(variant=variant)
        except Exception:
            logger.exception("Failed to train variant %s — continuing.", variant)

    logger.info("All variants done.")


if __name__ == "__main__":
    main()
