"""
backend/modeling/train_model.py

Trains an XGBoost model to predict NRFI probability and compares it against
a logistic regression baseline.

Features used (all pre-game, no leakage):
  Prior-season Fangraphs stats:
    home_sp_era, home_sp_fip, home_sp_whip, home_sp_k_pct, home_sp_bb_pct, home_sp_hr9
    away_sp_era, away_sp_fip, away_sp_whip, away_sp_k_pct, away_sp_bb_pct, away_sp_hr9
  Within-season rolling stats (last 5 starts):
    home_sp_last5_era, home_sp_last5_whip, home_sp_first_inn_era
    home_sp_avg_velo, home_sp_velo_trend, home_sp_days_rest
    away_sp_last5_era, away_sp_last5_whip, away_sp_first_inn_era
    away_sp_avg_velo, away_sp_velo_trend, away_sp_days_rest
  Team offense:
    home_team_first_inn_runs_per_game, away_team_first_inn_runs_per_game
    home_team_obp, away_team_obp, home_team_slg, away_team_slg
  Game-specific lineup strength (prior-season avg OBP of starting 9):
    home_lineup_obp, away_lineup_obp
  Park:
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
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
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
    # Prior-season Fangraphs pitcher stats
    "home_sp_era",
    "home_sp_fip",
    "home_sp_whip",
    "home_sp_k_pct",
    "home_sp_bb_pct",
    "home_sp_hr9",
    "away_sp_era",
    "away_sp_fip",
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
    # Team offense
    "home_team_first_inn_runs_per_game",
    "away_team_first_inn_runs_per_game",
    "home_team_obp",
    "away_team_obp",
    "home_team_slg",
    "away_team_slg",
    # Park
    "park_factor",
    # Weather
    "temperature_f",
    "wind_speed_mph",
    "wind_out_mph",
    "is_dome",
    # Umpire
    "ump_nrfi_rate_above_avg",
    # Game-specific lineup strength (prior-season avg OBP of starting 9)
    "home_lineup_obp",
    "away_lineup_obp",
    # Interaction features (derived at load time)
    "park_x_wind_out",        # park_factor × wind_out_mph  — park + wind together
    "home_sp_era_minus_away", # home_sp_era − away_sp_era  — relative pitcher quality
    "lineup_obp_diff",        # away_lineup_obp − home_lineup_obp — net offensive matchup
    # First-inning specific Statcast features (season-to-date prior starts)
    "home_sp_first_inn_k_pct",
    "home_sp_first_inn_bb_pct",
    "home_sp_first_inn_hard_pct",
    "away_sp_first_inn_k_pct",
    "away_sp_first_inn_bb_pct",
    "away_sp_first_inn_hard_pct",
    # Market prior — vig-removed implied P(NRFI) from bookmaker line (NULL → imputed to median)
    "p_nrfi_market",
]

# Earliest season included — 2023+ has real NRFI odds data for p_nrfi_market feature
_DATA_START_YEAR = 2023

# Rolling validation window: most recent K days are held out for val/calibration.
# Everything older is training. Live/future games are never touched.
_VAL_WINDOW_DAYS = 7


def load_feature_dataframe() -> pd.DataFrame:
    """
    Load NrfiFeatures joined with Game.game_date from the DB.
    Returns a DataFrame sorted chronologically with interaction features added.
    """
    # Base DB columns (exclude derived interaction features)
    _DERIVED = {"park_x_wind_out", "home_sp_era_minus_away", "lineup_obp_diff"}
    _BASE_COLS = [c for c in FEATURE_COLS if c not in _DERIVED]

    db = SessionLocal()
    try:
        rows = (
            db.query(NrfiFeatures, Game.game_date)
            .join(Game, NrfiFeatures.game_id == Game.id)
            .filter(
                NrfiFeatures.nrfi_label.isnot(None),
                Game.game_date >= f"{_DATA_START_YEAR}-01-01",
            )
            .order_by(Game.game_date)
            .all()
        )
    finally:
        db.close()

    records = []
    for feat, game_date in rows:
        record: dict[str, Any] = {"game_date": game_date, "nrfi_label": feat.nrfi_label}
        for col in _BASE_COLS:
            record[col] = getattr(feat, col, None)
        records.append(record)

    df = pd.DataFrame(records)

    # Derived interaction features (NaN-safe — NaN propagates when either input is NaN)
    df["park_x_wind_out"]        = df["park_factor"] * df["wind_out_mph"]
    df["home_sp_era_minus_away"] = df["home_sp_era"] - df["away_sp_era"]
    df["lineup_obp_diff"]        = df["away_lineup_obp"] - df["home_lineup_obp"]

    return df


def _audit_nrfi_rates(df: pd.DataFrame) -> None:
    """Log NRFI rate by season — sanity check that labels look correct."""
    df = df.copy()
    df["year"] = pd.to_datetime(df["game_date"]).dt.year
    logger.info("--- NRFI Rate Audit by Season ---")
    for year, grp in df.groupby("year"):
        rate = grp["nrfi_label"].mean()
        n = len(grp)
        logger.info("  %d:  %.1f%% NRFI  (%d games)", year, rate * 100, n)
    overall = df["nrfi_label"].mean()
    logger.info("  Overall: %.1f%% NRFI  (%d games)", overall * 100, len(df))


def date_based_split(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Expanding-window + rolling-validation split based on current date.

    Train : all completed games from _DATA_START_YEAR up to (today - _VAL_WINDOW_DAYS)
    Val   : completed games within the most recent _VAL_WINDOW_DAYS days
    Test  : today and future games (empty at train time — live evaluation only)

    This means completed 2026 games automatically enter training once they age
    past the validation window. The model is never trained on future games.
    """
    today = date.today()
    cutoff = today - timedelta(days=_VAL_WINDOW_DAYS)
    game_dates = pd.to_datetime(df["game_date"]).dt.date

    train = df[game_dates <= cutoff]
    val   = df[(game_dates > cutoff) & (game_dates < today)]
    test  = df[game_dates >= today]
    return train, val, test


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

    _audit_nrfi_rates(df)

    train_df, val_df, test_df = date_based_split(df)
    today = date.today()
    cutoff = today - timedelta(days=_VAL_WINDOW_DAYS)
    logger.info(
        "Split — train: %d games (through %s)  |  val: %d games (%s – %s)  |  test (live): %d",
        len(train_df), cutoff,
        len(val_df), cutoff + timedelta(days=1), today - timedelta(days=1),
        len(test_df),
    )
    if len(val_df) < 50:
        logger.warning(
            "Val set has only %d games — consider increasing _VAL_WINDOW_DAYS.", len(val_df)
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
    logger.info("--- Comparison (Val set) ---")
    logger.info(
        "  Logistic Regression — AUC: %.4f  |  Brier: %.4f",
        lr_val["auc"], lr_val["brier"],
    )
    logger.info(
        "  XGBoost             — AUC: %.4f  |  Brier: %.4f",
        xgb_val["auc"], xgb_val["brier"],
    )

    # -----------------------------------------------------------------------
    # Pick winner on val AUC
    # -----------------------------------------------------------------------
    if xgb_val["auc"] >= lr_val["auc"]:
        winner_name, winner = "XGBoost", xgb_model
    else:
        winner_name, winner = "Logistic Regression", lr_model
    logger.info("Winner: %s (val AUC %.4f)", winner_name, (xgb_val if winner_name == "XGBoost" else lr_val)["auc"])

    # -----------------------------------------------------------------------
    # Calibrate winner with Platt scaling on val set
    # -----------------------------------------------------------------------
    logger.info("Calibrating %s on val set...", winner_name)
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
    logger.info("Saved %s to %s", winner_name, output_path)

    # Write metadata so picks can always be traced to the model version that made them
    winner_val = xgb_val if winner_name == "XGBoost" else lr_val
    meta = {
        "trained_at": datetime.now().isoformat(),
        "winner": winner_name,
        "val_window_days": _VAL_WINDOW_DAYS,
        "train_start": str(train_df["game_date"].min()),
        "train_end": str(train_df["game_date"].max()),
        "train_games": len(train_df),
        "val_start": str(val_df["game_date"].min()) if len(val_df) else None,
        "val_end": str(val_df["game_date"].max()) if len(val_df) else None,
        "val_games": len(val_df),
        "val_auc": round(winner_val["auc"], 4),
        "val_auc_calibrated": round(cal_val["auc"], 4),
        "val_brier_calibrated": round(cal_val["brier"], 4),
    }
    meta_path = Path(output_path).with_suffix(".meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Metadata saved to %s", meta_path)

    return calibrated


def main() -> None:
    parser = argparse.ArgumentParser(description="Train NRFI model (XGBoost vs LogReg comparison).")
    parser.add_argument("--output", default=DEFAULT_MODEL_PATH)
    args = parser.parse_args()
    train(output_path=args.output)


if __name__ == "__main__":
    main()
