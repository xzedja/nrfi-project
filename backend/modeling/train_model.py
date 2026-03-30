"""
backend/modeling/train_model.py

Trains an XGBoost model to predict NRFI probability and compares it against
a logistic regression baseline.

Features used (all pre-game, no leakage):
  Prior-season Fangraphs stats:
    home_sp_era, home_sp_whip, home_sp_k_pct, home_sp_bb_pct, home_sp_hr9
    away_sp_era, away_sp_whip, away_sp_k_pct, away_sp_bb_pct, away_sp_hr9
  Within-season rolling stats (last 5 starts):
    home_sp_last5_era, home_sp_last5_whip, home_sp_first_inn_era
    home_sp_avg_velo, home_sp_velo_trend
    away_sp_last5_era, away_sp_last5_whip, away_sp_first_inn_era
    away_sp_avg_velo, away_sp_velo_trend
  Team and park:
    home_team_first_inn_runs_per_game
    away_team_first_inn_runs_per_game
    park_factor
  Weather (None for dome parks, imputed to median):
    temperature_f, wind_speed_mph, wind_out_mph, is_dome
  Umpire:
    ump_nrfi_rate_above_avg

Split strategy: chronological (no shuffling) — prevents future leakage.

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
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression as _PlattLR
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

sys.path.insert(0, ".")

from backend.db.models import Game, NrfiFeatures
from backend.db.session import SessionLocal
from backend.modeling.model_classes import CalibratedModel, SeasonStartImputer, XGBModel
from backend.modeling.model_store import DEFAULT_MODEL_PATH, save_model

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

FEATURE_COLS = [
    # Prior-season Fangraphs stats
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
    # Within-season rolling (last 5 starts)
    "home_sp_last5_era",
    "home_sp_last5_whip",
    "home_sp_first_inn_era",
    "home_sp_avg_velo",
    "home_sp_velo_trend",
    "home_sp_days_rest",
    "away_sp_last5_era",
    "away_sp_last5_whip",
    "away_sp_first_inn_era",
    "away_sp_avg_velo",
    "away_sp_velo_trend",
    "away_sp_days_rest",
    # Team and park
    "home_team_first_inn_runs_per_game",
    "away_team_first_inn_runs_per_game",
    "park_factor",
    # Weather
    "temperature_f",
    "wind_speed_mph",
    "wind_out_mph",
    "is_dome",
    # Umpire
    "ump_nrfi_rate_above_avg",
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
            record[col] = getattr(feat, col, None)
        records.append(record)

    return pd.DataFrame(records)


def chronological_split(
    df: pd.DataFrame, val_frac: float = 0.10, test_frac: float = 0.10
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split df into train / val / test by time order (no shuffling)."""
    n = len(df)
    test_start = int(n * (1 - test_frac))
    val_start = int(n * (1 - test_frac - val_frac))
    return df.iloc[:val_start], df.iloc[val_start:test_start], df.iloc[test_start:]


def evaluate(label: str, model: Any, X: pd.DataFrame, y: pd.Series) -> dict[str, float]:
    """Log and return AUC, log loss, and Brier score for a split."""
    probs = model.predict_proba(X)[:, 1]
    auc = roc_auc_score(y, probs)
    ll = log_loss(y, probs)
    brier = brier_score_loss(y, probs)
    logger.info(
        "%s — AUC: %.4f  |  Log Loss: %.4f  |  Brier: %.4f", label, auc, ll, brier
    )
    return {"auc": auc, "log_loss": ll, "brier": brier}





def _build_logistic_pipeline() -> Pipeline:
    return Pipeline([
        ("imputer", SeasonStartImputer()),
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, random_state=42)),
    ])


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

    # -----------------------------------------------------------------------
    # Baseline: logistic regression
    # -----------------------------------------------------------------------
    logger.info("--- Logistic Regression (baseline) ---")
    lr_model = _build_logistic_pipeline()
    lr_model.fit(X_train, y_train)
    evaluate("LR  Train", lr_model, X_train, y_train)
    lr_val = evaluate("LR  Val  ", lr_model, X_val, y_val)
    lr_test = evaluate("LR  Test ", lr_model, X_test, y_test)

    coefs = lr_model.named_steps["clf"].coef_[0]
    logger.info("LR feature coefficients (positive = increases P(NRFI)):")
    for feat, coef in sorted(zip(FEATURE_COLS, coefs), key=lambda x: -abs(x[1])):
        logger.info("  %-45s  %+.4f", feat, coef)

    # -----------------------------------------------------------------------
    # XGBoost with early stopping on validation set
    # -----------------------------------------------------------------------
    logger.info("--- XGBoost (early stopping on val set) ---")
    xgb_model = XGBModel()
    xgb_model.fit(X_train, y_train, X_val=X_val, y_val=y_val)
    evaluate("XGB Train", xgb_model, X_train, y_train)
    xgb_val = evaluate("XGB Val  ", xgb_model, X_val, y_val)
    xgb_test = evaluate("XGB Test ", xgb_model, X_test, y_test)

    importances = xgb_model.clf_.feature_importances_
    logger.info("XGBoost feature importances (gain):")
    for feat, imp in sorted(zip(FEATURE_COLS, importances), key=lambda x: -x[1]):
        logger.info("  %-45s  %.4f", feat, imp)

    # -----------------------------------------------------------------------
    # Summary comparison
    # -----------------------------------------------------------------------
    logger.info("--- Comparison (Test set) ---")
    logger.info(
        "  Logistic Regression — AUC: %.4f  |  Brier: %.4f",
        lr_test["auc"], lr_test["brier"],
    )
    logger.info(
        "  XGBoost             — AUC: %.4f  |  Brier: %.4f",
        xgb_test["auc"], xgb_test["brier"],
    )

    # -----------------------------------------------------------------------
    # Pick winner on val AUC, then calibrate on val set
    # -----------------------------------------------------------------------
    if xgb_val["auc"] >= lr_val["auc"]:
        winner_name, winner = "XGBoost", xgb_model
    else:
        winner_name, winner = "Logistic Regression", lr_model

    logger.info("Winner: %s (val AUC %.4f) — calibrating on val set...", winner_name, max(xgb_val["auc"], lr_val["auc"]))

    raw_val_probs = winner.predict_proba(X_val)[:, 1].reshape(-1, 1)
    platt = _PlattLR(C=1.0, max_iter=1000)
    platt.fit(raw_val_probs, y_val)
    calibrated = CalibratedModel(winner, platt)

    cal_val  = evaluate("Calibrated Val ", calibrated, X_val,  y_val)
    cal_test = evaluate("Calibrated Test", calibrated, X_test, y_test)
    logger.info(
        "Calibration effect on Brier (test): %.4f → %.4f",
        (xgb_test if winner_name == "XGBoost" else lr_test)["brier"],
        cal_test["brier"],
    )

    save_model(calibrated, output_path)
    logger.info("Saved calibrated %s to %s", winner_name, output_path)
    return calibrated


def main() -> None:
    parser = argparse.ArgumentParser(description="Train NRFI model (XGBoost vs LogReg comparison).")
    parser.add_argument("--output", default=DEFAULT_MODEL_PATH)
    args = parser.parse_args()
    train(output_path=args.output)


if __name__ == "__main__":
    main()
