"""
backend/modeling/evaluate_model.py

Evaluates the saved NRFI model against all labeled historical data.

Reports:
  - Overall AUC, log loss, Brier score
  - Per-season breakdown of the same metrics
  - Calibration: predicted P(NRFI) buckets vs actual NRFI rates
  - Edge analysis: when model edge vs market exceeds a threshold,
    does the model's predicted side win more often?

Usage:
    DATABASE_URL=postgresql://... python -m backend.modeling.evaluate_model
    DATABASE_URL=postgresql://... python -m backend.modeling.evaluate_model --season 2023
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

sys.path.insert(0, ".")

from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal
from backend.modeling.model_store import load_model
from backend.modeling.train_model import FEATURE_COLS

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_labeled_data(season: int | None = None) -> pd.DataFrame:
    """
    Load all labeled NrfiFeatures rows joined with game metadata.
    Optionally filter to a single season.
    """
    db = SessionLocal()
    try:
        q = (
            db.query(NrfiFeatures, Game.game_date, Game.home_team, Game.away_team)
            .join(Game, NrfiFeatures.game_id == Game.id)
            .filter(NrfiFeatures.nrfi_label.isnot(None))
            .order_by(Game.game_date)
        )
        if season is not None:
            from sqlalchemy import extract
            q = q.filter(extract("year", Game.game_date) == season)
        rows = q.all()
    finally:
        db.close()

    records: list[dict[str, Any]] = []
    for feat, game_date, home_team, away_team in rows:
        record: dict[str, Any] = {
            "game_date": game_date,
            "season": game_date.year,
            "home_team": home_team,
            "away_team": away_team,
            "nrfi_label": feat.nrfi_label,
            "p_nrfi_market": feat.p_nrfi_market,
        }
        for col in FEATURE_COLS:
            record[col] = getattr(feat, col, None)
        records.append(record)

    return pd.DataFrame(records)


def _metrics(y_true: pd.Series, probs: np.ndarray) -> dict[str, float]:
    """Return AUC, log loss, and Brier score."""
    return {
        "auc": roc_auc_score(y_true, probs),
        "log_loss": log_loss(y_true, probs),
        "brier": brier_score_loss(y_true, probs),
        "n": len(y_true),
        "nrfi_rate": float(y_true.mean()),
    }


def print_metrics(label: str, m: dict[str, float]) -> None:
    logger.info(
        "%-30s  n=%5d  NRFI%%=%.1f%%  AUC=%.4f  LogLoss=%.4f  Brier=%.4f",
        label,
        int(m["n"]),
        m["nrfi_rate"] * 100,
        m["auc"],
        m["log_loss"],
        m["brier"],
    )


def calibration_table(
    y_true: pd.Series, probs: np.ndarray, n_bins: int = 10
) -> pd.DataFrame:
    """
    Bin predictions into equal-width buckets and compare predicted vs actual NRFI rate.
    """
    bins = np.linspace(0, 1, n_bins + 1)
    labels = [f"{bins[i]:.1f}–{bins[i+1]:.1f}" for i in range(n_bins)]
    bucket = pd.cut(probs, bins=bins, labels=labels, include_lowest=True)

    df = pd.DataFrame({"bucket": bucket, "pred": probs, "actual": y_true.values})
    agg = (
        df.groupby("bucket", observed=False)
        .agg(n=("actual", "count"), mean_pred=("pred", "mean"), actual_rate=("actual", "mean"))
        .reset_index()
    )
    agg["diff"] = agg["actual_rate"] - agg["mean_pred"]
    return agg


def edge_analysis(
    y_true: pd.Series,
    probs: np.ndarray,
    market: pd.Series,
    thresholds: list[float] | None = None,
) -> None:
    """
    For games where model edge (p_model - p_market) exceeds a threshold,
    report actual NRFI rate vs market implied rate.
    """
    if thresholds is None:
        thresholds = [0.03, 0.05, 0.08, 0.10]

    has_market = market.notna()
    if has_market.sum() == 0:
        logger.info("No market odds available — skipping edge analysis.")
        return

    edge = probs - market.values
    logger.info("\n--- Edge Analysis (model - market > threshold) ---")
    logger.info("%-10s  %-8s  %-12s  %-12s", "Threshold", "N games", "Actual NRFI%", "Market NRFI%")

    for t in thresholds:
        mask = has_market & (edge > t)
        n = mask.sum()
        if n < 5:
            logger.info(">= %+.2f      %-8d  (too few games)", t, n)
            continue
        actual = y_true[mask].mean()
        mkt_implied = market[mask].mean()
        logger.info(">= %+.2f      %-8d  %.1f%%          %.1f%%", t, n, actual * 100, mkt_implied * 100)


def evaluate(season: int | None = None) -> None:
    logger.info("Loading model...")
    model = load_model()

    logger.info("Loading labeled data%s...", f" for {season}" if season else "")
    df = load_labeled_data(season)

    if df.empty:
        logger.error("No labeled data found. Run the backfill and retrain first.")
        return

    logger.info("Loaded %d labeled games.", len(df))

    X = df[FEATURE_COLS]
    y = df["nrfi_label"].astype(int)
    probs = model.predict_proba(X)[:, 1]

    # ------------------------------------------------------------------
    # Overall metrics
    # ------------------------------------------------------------------
    logger.info("\n--- Overall metrics ---")
    print_metrics("All seasons", _metrics(y, probs))

    # ------------------------------------------------------------------
    # Per-season breakdown
    # ------------------------------------------------------------------
    logger.info("\n--- Per-season metrics ---")
    for yr, grp in df.groupby("season"):
        X_s = grp[FEATURE_COLS]
        y_s = grp["nrfi_label"].astype(int)
        if y_s.nunique() < 2:
            logger.info("Season %s: skipped (only one class present)", yr)
            continue
        p_s = model.predict_proba(X_s)[:, 1]
        print_metrics(f"Season {yr}", _metrics(y_s, p_s))

    # ------------------------------------------------------------------
    # Calibration table
    # ------------------------------------------------------------------
    logger.info("\n--- Calibration (predicted vs actual NRFI rate) ---")
    cal = calibration_table(y, probs)
    logger.info("%-12s  %6s  %10s  %11s  %6s", "Bucket", "N", "Mean pred", "Actual rate", "Diff")
    for _, row in cal.iterrows():
        if row["n"] == 0:
            continue
        logger.info(
            "%-12s  %6d  %10.3f  %11.3f  %+6.3f",
            row["bucket"], int(row["n"]), row["mean_pred"], row["actual_rate"], row["diff"],
        )

    # ------------------------------------------------------------------
    # Edge analysis
    # ------------------------------------------------------------------
    edge_analysis(y, probs, df["p_nrfi_market"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the saved NRFI model on historical data.")
    parser.add_argument(
        "--season", type=int, default=None,
        help="Restrict evaluation to a single season (default: all seasons).",
    )
    args = parser.parse_args()
    evaluate(season=args.season)


if __name__ == "__main__":
    main()
