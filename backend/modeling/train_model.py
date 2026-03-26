"""
backend/modeling/train_model.py

Trains a baseline logistic regression model to predict NRFI probability.

Features used (all pre-game, no leakage):
  - home_sp_era, home_sp_whip, home_sp_k_pct, home_sp_bb_pct, home_sp_hr9
  - away_sp_era, away_sp_whip, away_sp_k_pct, away_sp_bb_pct, away_sp_hr9
  - home_team_first_inn_runs_per_game
  - away_team_first_inn_runs_per_game
  - park_factor

Split strategy: chronological (no shuffling) to respect time ordering and
prevent future data from leaking into training.

Usage:
    DATABASE_URL=postgresql://... python -m backend.modeling.train_model
    DATABASE_URL=postgresql://... python -m backend.modeling.train_model --output models/nrfi_model.pkl
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, ".")

from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal
from backend.modeling.model_store import DEFAULT_MODEL_PATH, save_model

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "home_sp_era",
    "home_sp_whip",
    "home_sp_k_pct",
    "home_sp_bb_pct",
    "home_sp_hr9",
    "away_sp_era",
    "away_sp_whip",
    "away_sp_k_pct",
    "away_sp_bb_pct",
    "away_sp_hr9",
    "home_team_first_inn_runs_per_game",
    "away_team_first_inn_runs_per_game",
    "park_factor",
]


def load_feature_dataframe() -> pd.DataFrame:
    """
    Load NrfiFeatures joined with Game.game_date from the DB.
    Returns a DataFrame sorted chronologically.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(NrfiFeatures, Game.game_date)
            .join(Game, NrfiFeatures.game_id == Game.id)
            .filter(NrfiFeatures.nrfi_label.isnot(None))
            .order_by(Game.game_date)
            .all()
        )
    finally:
        db.close()

    records = []
    for feat, game_date in rows:
        record: dict[str, Any] = {"game_date": game_date, "nrfi_label": feat.nrfi_label}
        for col in FEATURE_COLS:
            record[col] = getattr(feat, col)
        records.append(record)

    return pd.DataFrame(records)


def chronological_split(
    df: pd.DataFrame, val_frac: float = 0.10, test_frac: float = 0.10
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split df into train / val / test by time order (no shuffling).
    Default: 80% train, 10% val, 10% test.
    """
    n = len(df)
    test_start = int(n * (1 - test_frac))
    val_start = int(n * (1 - test_frac - val_frac))
    return df.iloc[:val_start], df.iloc[val_start:test_start], df.iloc[test_start:]


def evaluate(label: str, model: Pipeline, X: pd.DataFrame, y: pd.Series) -> None:
    """Log AUC, log loss, and Brier score for a split."""
    probs = model.predict_proba(X)[:, 1]
    auc = roc_auc_score(y, probs)
    ll = log_loss(y, probs)
    brier = brier_score_loss(y, probs)
    logger.info(
        "%s — AUC: %.4f  |  Log Loss: %.4f  |  Brier: %.4f", label, auc, ll, brier
    )


def train(output_path: str = DEFAULT_MODEL_PATH) -> Pipeline:
    df = load_feature_dataframe()
    logger.info("Loaded %d labeled rows from DB", len(df))

    if len(df) < 100:
        raise ValueError("Not enough labeled data to train. Run the backfill first.")

    train_df, val_df, test_df = chronological_split(df)
    logger.info(
        "Split — train: %d  |  val: %d  |  test: %d",
        len(train_df), len(val_df), len(test_df),
    )

    X_train = train_df[FEATURE_COLS]
    y_train = train_df["nrfi_label"].astype(int)
    X_val = val_df[FEATURE_COLS]
    y_val = val_df["nrfi_label"].astype(int)
    X_test = test_df[FEATURE_COLS]
    y_test = test_df["nrfi_label"].astype(int)

    # Pipeline: impute missing values with median, scale, then logistic regression
    model = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, random_state=42)),
    ])

    model.fit(X_train, y_train)
    logger.info("Training complete.")

    evaluate("Train", model, X_train, y_train)
    evaluate("Val  ", model, X_val, y_val)
    evaluate("Test ", model, X_test, y_test)

    # Log feature coefficients so we can sanity-check directions
    coefs = model.named_steps["clf"].coef_[0]
    logger.info("Feature coefficients (positive = increases P(NRFI)):")
    for feat, coef in sorted(zip(FEATURE_COLS, coefs), key=lambda x: -abs(x[1])):
        logger.info("  %-40s  %+.4f", feat, coef)

    save_model(model, output_path)
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description="Train NRFI logistic regression model.")
    parser.add_argument("--output", default=DEFAULT_MODEL_PATH)
    args = parser.parse_args()
    train(output_path=args.output)


if __name__ == "__main__":
    main()
